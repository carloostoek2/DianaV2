"""TurnOrchestrator — VIP message use-case wiring (supervised + autonomous send)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from diana.application.admin_service import AdminService
from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.gray_zone_service import GrayZoneService
from diana.application.observability import log_swallowed
from diana.application.owner_history import append_owner_delivery_history
from diana.application.ports import (
    BehaviorDeliverer,
    DeliveryContext,
    DeliveryMode,
    DeliveryResult,
    DeliveryResultWriter,
    MessageHistoryWriter,
    RuntimeTimerRecord,
    RuntimeTimerStore,
    VipInboundMessage,
    VipStore,
)
from diana.behavior.ports import DelayPolicy
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.exceptions import (
    AnalystSchemaInvalidError,
    ContextExceedsLimitError,
    EvaluatorSchemaInvalidError,
    GeneratorEmptyOutputError,
    TurnSupersededError,
)
from diana.cognitive.models import (
    Decision,
    IncomingTurn,
    TurnStatus,
    is_turn_status_terminal,
)

logger = logging.getLogger("diana.application")

# Open VIP burst: trailing consecutive role=vip lines since last owner/bot reply.
_BURST_HISTORY_LIMIT = 40
_MULTI_VIP_BURST_HEADER = "(el VIP envió varios mensajes seguidos)"


def trailing_vip_texts(history_rows: list[dict]) -> list[str]:
    """Extract chronological texts of the open trailing VIP burst from history."""
    texts_rev: list[str] = []
    for row in reversed(history_rows):
        if not isinstance(row, dict):
            break
        if row.get("role") != "vip":
            break
        texts_rev.append(str(row.get("text") or ""))
    texts_rev.reverse()
    return [t for t in texts_rev if t.strip()]


def format_vip_burst_text(texts: list[str], *, fallback: str) -> str:
    """Build IncomingTurn.text for a single msg or multi-msg open burst.

    ROADMAP 3.3: when a VIP sends multiple messages before the pipeline runs,
    number each line so the Analyst can reason about distinct intents within
    the burst instead of collapsing N intents into a single ``intent``
    field. The Generator still produces one reply — the numbering is for the
    cognitive stage only — but the owner can see all N intents in ``/traza``
    and notice if one was ignored.
    """
    cleaned = [t.strip() for t in texts if isinstance(t, str) and t.strip()]
    if not cleaned:
        return fallback
    if len(cleaned) == 1:
        return cleaned[0]
    header = f"(el VIP envió {len(cleaned)} mensajes seguidos)"
    numbered = "\n".join(f"[{i + 1}/{len(cleaned)}] {t}" for i, t in enumerate(cleaned))
    return f"{header}\n{numbered}"


class DirectorPort(Protocol):
    async def handle_turn(self, turn_context: IncomingTurn) -> Decision: ...


class LearningPort(Protocol):
    async def run_post_turn(self, turn_id: UUID) -> object: ...


@dataclass(frozen=True, slots=True)
class _AutonomousDeliverJob:
    """Prepared autonomous deliver payload — executed outside chat_scope."""

    text: str
    ctx: DeliveryContext
    decision: Decision


class TurnOrchestrator:
    """Application entry for VIP business messages.

    Supervised approve never auto-delivers. Autonomous ``action=="send"``
    delivers via BehaviorEngine **outside** the per-chat lock so
    cancel_pending can interrupt mid-flight (Admin pattern).
    """

    def __init__(
        self,
        *,
        coordinator: TurnCoordinator,
        director: DirectorPort,
        admin: AdminService,
        learning: LearningPort,
        history: MessageHistoryWriter,
        gray_zone: GrayZoneService | None = None,
        feature_gray_zone_enabled: bool = False,
        behavior: BehaviorDeliverer | None = None,
        autonomous_mode: AutonomousModeService | None = None,
        vip_store: VipStore | None = None,
        traces: DeliveryResultWriter | None = None,
        delivery_mode: DeliveryMode = "supervised",
        feature_advanced_behavior: bool = False,
        sandbox: object | None = None,
        delay_policy: DelayPolicy | None = None,
        runtime_timers: RuntimeTimerStore | None = None,
        clock: object | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._director = director
        self._admin = admin
        self._learning = learning
        self._history = history
        self._gray_zone = gray_zone
        self._feature_gray_zone_enabled = feature_gray_zone_enabled
        self._behavior = behavior
        self._autonomous_mode = autonomous_mode
        self._vip_store = vip_store
        self._traces = traces
        self._delivery_mode = delivery_mode
        self._feature_advanced_behavior = bool(feature_advanced_behavior)
        self._sandbox = sandbox
        self._delay_policy = delay_policy
        self._runtime_timers = runtime_timers
        self._clock = clock

    def _sandbox_active(self, chat_id: int) -> bool:
        return self._sandbox is not None and self._sandbox.is_active(chat_id)  # type: ignore[union-attr]

    def _effective_delivery_mode(self, _chat_id: int) -> DeliveryMode:
        # Sandbox must not force fake_delivery; product isolation is should_persist.
        return self._delivery_mode

    async def _resolve_effective_mode(
        self, vip_id: UUID | None
    ) -> DeliveryMode:
        """Resolve the mode used for the pre-pipeline delay.

        Autonomous mode must pass both L1 (feature flag) and L2
        (global mode or per-VIP auto_send) gates. Falls back to
        supervised otherwise.
        """
        mode = self._delivery_mode
        if mode != "autonomous":
            return mode
        if self._autonomous_mode is None:
            return "supervised"
        enabled = await self._autonomous_mode.is_autonomous_enabled(vip_id)
        return "autonomous" if enabled else "supervised"

    async def _maybe_post_turn(self, turn_id: UUID, chat_id: int) -> None:
        if self._sandbox is not None and not self._sandbox.should_persist(chat_id):  # type: ignore[union-attr]
            logger.info(
                "post_turn_skipped_sandbox",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return
        await self._learning.run_post_turn(turn_id)

    async def _safe_notify_info(
        self,
        message: str,
        *,
        chat_id: int,
        event: str,
        **extra: object,
    ) -> None:
        """Owner notify fail-soft: never mask the primary failure path."""
        try:
            await self._admin.notify_info(message, chat_id=chat_id)
        except Exception:
            log_swallowed(logger, event, chat_id=chat_id, **extra)

    async def _fail_director_typed(
        self,
        turn_id: UUID,
        chat_id: int,
        *,
        error: str,
        notify_event: str,
    ) -> None:
        """mark_failed then fail-soft owner notify (typed director errors)."""
        await self._coordinator.mark_failed(turn_id, error=error)
        await self._safe_notify_info(
            f"Turn {turn_id} failed: {error}",
            chat_id=chat_id,
            event=notify_event,
            turn_id=str(turn_id),
        )

    async def handle_vip_message(self, incoming: VipInboundMessage) -> UUID:
        """Process one VIP message; return the minted turn_id."""
        chat_id = incoming.chat_id
        # Capture before any await so owner marks during pre-mint are visible.
        before_inbound = time.monotonic()
        bc = incoming.business_connection_id
        if bc is None or not str(bc).strip():
            # Fail under lock without advancing VIP epoch / durable history.
            async with self._coordinator.chat_scope(chat_id):
                turn_id, _ = await self._handle_vip_message_locked(
                    incoming, vip_epoch=None
                )
            return turn_id

        # Newer VIP message invalidates older in-flight work for this chat.
        vip_epoch = self._coordinator.bump_vip_epoch(chat_id)
        await self._append_vip_history_if_persist(incoming)

        # Mint ASAP under lock (before mode resolve / delay) so owner cancel
        # has a durable target; sleep stays OUTSIDE chat_scope.
        async with self._coordinator.chat_scope(chat_id):
            if not self._coordinator.is_vip_epoch_current(chat_id, vip_epoch):
                winner_id = await self._resolve_skip_mint_turn_id(chat_id)
                logger.info(
                    "turn_mint_skipped_stale_epoch",
                    extra={
                        "chat_id": chat_id,
                        "vip_epoch": vip_epoch,
                        "current_epoch": self._coordinator.current_vip_epoch(
                            chat_id
                        ),
                        "winner_turn_id": str(winner_id),
                    },
                )
                return winner_id
            turn_id, aborted_owner = await self._mint_turn_for_inbound(
                incoming,
                vip_epoch,
                before_inbound=before_inbound,
            )
            if aborted_owner:
                return turn_id

        mode = await self._resolve_effective_mode(incoming.vip_id)
        pre_delay = (
            self._delay_policy.initial_delay_seconds(mode)
            if self._delay_policy is not None
            else 0.0
        )

        logger.info(
            "turn_delay_started",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "pre_delay_s": pre_delay,
                "mode": mode,
            },
        )
        timer_id: UUID | None = None
        if pre_delay > 0:
            timer_id = await self._persist_pre_delay_timer(
                turn_id=turn_id,
                incoming=incoming,
                vip_epoch=vip_epoch,
                pre_delay=pre_delay,
                mode=mode,
            )
            try:
                await self._sleep_seconds(pre_delay)
            finally:
                if timer_id is not None and self._runtime_timers is not None:
                    try:
                        await self._runtime_timers.mark_completed(timer_id)
                    except Exception:
                        log_swallowed(
                            logger,
                            "pre_delay_timer_complete_failed",
                            turn_id=str(turn_id),
                            timer_id=str(timer_id),
                        )

        return await self._run_after_pre_delay(
            incoming,
            turn_id=turn_id,
            vip_epoch=vip_epoch,
            before_inbound=before_inbound,
        )

    async def resume_waiting_delay(
        self,
        *,
        turn_id: UUID,
        incoming: VipInboundMessage,
        vip_epoch: int,
        remaining_seconds: float,
    ) -> UUID:
        """Startup recovery: finish pre-pipeline wait then run cognitive path.

        Call **after** missed-update recovery so offline owner/VIP traffic can
        supersede the turn first.
        """
        chat_id = incoming.chat_id
        self._coordinator.restore_vip_epoch(chat_id, vip_epoch)
        self._coordinator.bind_turn_vip_epoch(turn_id, chat_id, vip_epoch)

        live = await self._coordinator.get_turn(turn_id)
        if live is None or live.status != TurnStatus.WAITING_DELAY.value:
            logger.info(
                "pre_delay_resume_skip",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "status": None if live is None else live.status,
                },
            )
            return turn_id

        if not self._coordinator.is_vip_epoch_current(chat_id, vip_epoch):
            async with self._coordinator.chat_scope(chat_id):
                still = await self._coordinator.get_turn(turn_id)
                if still is not None and not is_turn_status_terminal(still.status):
                    await self._coordinator.supersede_chat(
                        chat_id,
                        reason="new_message",
                        superseded_by=None,
                    )
            logger.info(
                "pre_delay_resume_stale_epoch",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_epoch": vip_epoch,
                },
            )
            return turn_id

        logger.info(
            "pre_delay_resume_started",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "remaining_s": remaining_seconds,
            },
        )
        if remaining_seconds > 0:
            await self._sleep_seconds(remaining_seconds)

        return await self._run_after_pre_delay(
            incoming,
            turn_id=turn_id,
            vip_epoch=vip_epoch,
            before_inbound=None,
        )

    async def _sleep_seconds(self, seconds: float) -> None:
        if seconds <= 0:
            return
        sleep = getattr(self._clock, "sleep", None) if self._clock is not None else None
        if callable(sleep):
            await sleep(seconds)
            return
        await asyncio.sleep(seconds)

    async def _persist_pre_delay_timer(
        self,
        *,
        turn_id: UUID,
        incoming: VipInboundMessage,
        vip_epoch: int,
        pre_delay: float,
        mode: str,
    ) -> UUID | None:
        if self._runtime_timers is None or pre_delay <= 0:
            return None
        now = (
            self._clock.now()  # type: ignore[union-attr]
            if self._clock is not None and hasattr(self._clock, "now")
            else datetime.now(UTC)
        )
        timer_id = uuid4()
        payload = {
            "vip_epoch": vip_epoch,
            "mode": mode,
            "incoming": {
                "chat_id": incoming.chat_id,
                "text": incoming.text,
                "telegram_message_id": incoming.telegram_message_id,
                "business_connection_id": incoming.business_connection_id,
                "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                "is_edit": bool(incoming.is_edit),
            },
        }
        try:
            await self._runtime_timers.create_active(
                RuntimeTimerRecord(
                    id=timer_id,
                    chat_id=incoming.chat_id,
                    turn_id=turn_id,
                    delivery_id=None,
                    kind="pre_delay",
                    scheduled_at=now,
                    initial_delay_seconds=float(pre_delay),
                    status="active",
                    created_at=now,
                    payload=payload,
                )
            )
            return timer_id
        except Exception:
            logger.exception(
                "pre_delay_timer_persist_failed",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            return None

    async def _run_after_pre_delay(
        self,
        incoming: VipInboundMessage,
        *,
        turn_id: UUID,
        vip_epoch: int,
        before_inbound: float | None,
    ) -> UUID:
        """Post-wait gates + cognitive pipeline (shared by live path and recovery)."""
        chat_id = incoming.chat_id
        # Re-check after delay (no long lock): terminal / stale epoch / owner flag.
        live = await self._coordinator.get_turn(turn_id)
        owner_flag = self._coordinator.is_owner_intervened(
            chat_id, since=before_inbound
        )
        if live is None or is_turn_status_terminal(live.status):
            reason = self._abort_reason_after_delay(
                live, owner_intervened=owner_flag
            )
            logger.info(
                "turn_aborted_after_delay",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "reason": reason,
                    "status": None if live is None else live.status,
                },
            )
            return turn_id

        if not self._coordinator.is_vip_epoch_current(chat_id, vip_epoch):
            async with self._coordinator.chat_scope(chat_id):
                still = await self._coordinator.get_turn(turn_id)
                if still is not None and not is_turn_status_terminal(still.status):
                    await self._coordinator.supersede_chat(
                        chat_id,
                        reason="new_message",
                        superseded_by=None,
                    )
                still = await self._coordinator.get_turn(turn_id)
            logger.info(
                "turn_aborted_after_delay",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "reason": "new_message",
                    "status": None if still is None else still.status,
                },
            )
            return turn_id

        if owner_flag:
            # Defense-in-depth: flag set but coordinate(owner) not yet applied.
            async with self._coordinator.chat_scope(chat_id):
                still = await self._coordinator.get_turn(turn_id)
                if still is not None and not is_turn_status_terminal(still.status):
                    await self._coordinator.supersede_chat(
                        chat_id,
                        reason="owner_message",
                        superseded_by=None,
                    )
                self._coordinator.clear_owner_intervention(chat_id)
                still = await self._coordinator.get_turn(turn_id)
            logger.info(
                "turn_aborted_after_delay",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "reason": "owner_message",
                    "status": None if still is None else still.status,
                },
            )
            return turn_id

        logger.info(
            "turn_delay_completed",
            extra={"turn_id": str(turn_id), "chat_id": chat_id},
        )

        pending_deliver: _AutonomousDeliverJob | None
        async with self._coordinator.chat_scope(chat_id):
            still = await self._coordinator.get_turn(turn_id)
            if still is None or is_turn_status_terminal(still.status):
                reason = self._abort_reason_after_delay(
                    still,
                    owner_intervened=self._coordinator.is_owner_intervened(
                        chat_id, since=before_inbound
                    ),
                )
                logger.info(
                    "turn_aborted_after_delay",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "reason": reason,
                        "status": None if still is None else still.status,
                    },
                )
                return turn_id
            if not self._coordinator.is_vip_epoch_current(chat_id, vip_epoch):
                if not is_turn_status_terminal(still.status):
                    await self._coordinator.supersede_chat(
                        chat_id,
                        reason="new_message",
                        superseded_by=None,
                    )
                still = await self._coordinator.get_turn(turn_id)
                logger.info(
                    "turn_aborted_after_delay",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "reason": "new_message",
                        "status": None if still is None else still.status,
                    },
                )
                return turn_id
            # Defense-in-depth: owner flag under lock before Director.
            if self._coordinator.is_owner_intervened(chat_id, since=before_inbound):
                await self._coordinator.supersede_chat(
                    chat_id,
                    reason="owner_message",
                    superseded_by=None,
                )
                self._coordinator.clear_owner_intervention(chat_id)
                still = await self._coordinator.get_turn(turn_id)
                logger.info(
                    "turn_aborted_after_delay",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "reason": "owner_message",
                        "status": None if still is None else still.status,
                    },
                )
                return turn_id
            turn_id, pending_deliver = await self._run_cognitive_after_delay(
                incoming, turn_id=turn_id, vip_epoch=vip_epoch
            )
            if pending_deliver is None:
                await self._maybe_post_turn(turn_id, chat_id)
                return turn_id

        # OUTSIDE lock — cancel_pending can interrupt delays (Admin pattern).
        # Re-check freeze after lock release (race: freeze applied mid-pipeline).
        vip_frozen = await self._is_vip_frozen(incoming.vip_id)
        if vip_frozen:
            async with self._coordinator.chat_scope(chat_id):
                live = await self._coordinator.get_turn(turn_id)
                if live is not None and not is_turn_status_terminal(live.status):
                    await self._coordinator.mark_failed(
                        turn_id, error="vip_frozen"
                    )
                    await self._safe_notify_info(
                        f"Turn {turn_id} failed: vip_frozen",
                        chat_id=chat_id,
                        event="owner_notify_failed_after_vip_frozen",
                        turn_id=str(turn_id),
                    )
            await self._maybe_post_turn(turn_id, chat_id)
            logger.info(
                "autonomous_vip_frozen_pre_deliver",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            return turn_id

        # Prepare already fails closed if behavior is None; re-check for
        # partial wiring / race without relying on assert (stripped under -O).
        if self._behavior is None:
            async with self._coordinator.chat_scope(chat_id):
                live = await self._coordinator.get_turn(turn_id)
                if live is not None and not is_turn_status_terminal(live.status):
                    await self._coordinator.mark_failed(
                        turn_id, error="autonomous_behavior_not_wired"
                    )
            await self._maybe_post_turn(turn_id, chat_id)
            logger.error(
                "autonomous_behavior_not_wired",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return turn_id

        # SEC-F2: pass actual freeze snapshot from re-check (False after gate).
        # Mid-delay FreezePort re-query remains residual (engine uses ctx only).
        deliver_ctx = pending_deliver.ctx.model_copy(
            update={"is_frozen": vip_frozen}
        )
        logger.info(
            "autonomous_send_start",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
            },
        )
        result = await self._behavior.deliver(
            [pending_deliver.text],
            deliver_ctx,
            turn_id,
            decision=pending_deliver.decision,
        )
        async with self._coordinator.chat_scope(chat_id):
            delivered = await self._finalize_autonomous_delivery(
                turn_id, chat_id, result, text=pending_deliver.text
            )

        # Near-threshold notify only when finalize confirmed DELIVERED
        # (not raw actuator success — mid-flight supersede must not notify).
        if (
            delivered
            and self._autonomous_mode is not None
        ):
            await self._autonomous_mode.notify_if_needed(
                turn_id,
                pending_deliver.decision,
                pending_deliver.decision.evaluation,
            )

        await self._maybe_post_turn(turn_id, chat_id)
        logger.info(
            "vip_message_handled",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "action": "send",
            },
        )
        return turn_id

    async def _append_vip_history_if_persist(self, incoming: VipInboundMessage) -> None:
        """Persist VIP inbound early so aborted rounds still join the open burst.

        Edits (same telegram_message_id) **replace** the prior row so the model
        never sees original + edited as two messages.
        """
        if (
            self._sandbox is not None
            and not self._sandbox.should_persist(incoming.chat_id)  # type: ignore[union-attr]
        ):
            logger.info(
                "vip_history_skipped_sandbox",
                extra={"chat_id": incoming.chat_id},
            )
            return
        upsert = getattr(self._history, "upsert_vip_message", None)
        if callable(upsert) and (
            incoming.is_edit or incoming.telegram_message_id is not None
        ):
            action = await upsert(
                incoming.chat_id,
                text=incoming.text,
                telegram_message_id=incoming.telegram_message_id,
            )
            if action == "updated" or incoming.is_edit:
                logger.info(
                    "vip_history_message_updated",
                    extra={
                        "chat_id": incoming.chat_id,
                        "telegram_message_id": incoming.telegram_message_id,
                        "is_edit": incoming.is_edit,
                    },
                )
            return
        await self._history.append(
            incoming.chat_id,
            role="vip",
            text=incoming.text,
            telegram_message_id=incoming.telegram_message_id,
        )

    async def _coalesce_open_vip_turn_text(
        self, chat_id: int, *, fallback: str
    ) -> str:
        """Join trailing unanswered VIP messages for the cognitive turn payload.

        History is the source of truth after append. When sandbox skips durable
        history, get_recent is empty and we keep ``fallback`` (current text only).
        """
        try:
            recent = await self._history.get_recent(
                chat_id, limit=_BURST_HISTORY_LIMIT
            )
        except Exception:
            logger.exception(
                "vip_burst_history_read_failed",
                extra={"chat_id": chat_id},
            )
            return fallback
        burst = trailing_vip_texts(recent)
        text = format_vip_burst_text(burst, fallback=fallback)
        if len(burst) > 1:
            logger.info(
                "vip_open_burst_coalesced",
                extra={
                    "chat_id": chat_id,
                    "burst_count": len(burst),
                    "text_chars": len(text),
                },
            )
        return text

    async def _resolve_skip_mint_turn_id(self, chat_id: int) -> UUID:
        """Prefer live winner, else last minted turn for chat; uuid4 last resort."""
        live_turns = await self._coordinator.list_non_terminal(chat_id)
        if live_turns:
            return live_turns[0].id
        last = self._coordinator.last_turn_id(chat_id)
        if last is not None:
            return last
        # Chat never minted a turn in this process — unavoidable synthetic.
        logger.info(
            "turn_mint_skipped_stale_epoch_no_prior_turn",
            extra={"chat_id": chat_id},
        )
        return uuid4()

    async def _mint_turn_for_inbound(
        self,
        incoming: VipInboundMessage,
        vip_epoch: int,
        *,
        before_inbound: float,
    ) -> tuple[UUID, bool]:
        """Create waiting_delay turn + bind epoch. Caller holds chat_scope.

        Returns ``(turn_id, aborted_for_owner)``. When owner intervened since
        *before_inbound*, cascade-supersedes the new turn and clears the flag.
        """
        chat_id = incoming.chat_id
        record = await self._coordinator.begin_turn_unlocked(
            chat_id=chat_id,
            trigger_message_id=incoming.telegram_message_id,
            vip_id=incoming.vip_id,
        )
        turn_id = record.id
        self._coordinator.bind_turn_vip_epoch(turn_id, chat_id, vip_epoch)
        logger.info(
            "turn_minted_waiting_delay",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "vip_epoch": vip_epoch,
            },
        )
        if self._coordinator.is_owner_intervened(chat_id, since=before_inbound):
            await self._coordinator.supersede_chat(
                chat_id,
                reason="owner_message",
                superseded_by=None,
            )
            self._coordinator.clear_owner_intervention(chat_id)
            logger.info(
                "turn_aborted_owner_at_mint",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "reason": "owner_message",
                },
            )
            return turn_id, True
        # Drop any older stuck flag so mid-pipeline checks stay clean.
        self._coordinator.clear_owner_intervention(chat_id)
        return turn_id, False

    @staticmethod
    def _abort_reason_after_delay(
        live: object | None,
        *,
        owner_intervened: bool = False,
    ) -> str:
        """Map post-delay abort for logs.

        - ``owner_message`` when owner flag/path fired
        - ``new_message`` when VIP replace (superseded_by set) or epoch stale
        - ``superseded`` neutral when terminal supersede without owner/VIP marker
          (e.g. sandbox reset)
        """
        if owner_intervened:
            return "owner_message"
        if live is None:
            return "new_message"
        status = getattr(live, "status", None)
        superseded_by = getattr(live, "superseded_by", None)
        if status in (TurnStatus.SUPERSEDED.value, "superseded"):
            if superseded_by is not None:
                return "new_message"
            return "superseded"
        return "new_message"

    async def _run_cognitive_after_delay(
        self,
        incoming: VipInboundMessage,
        *,
        turn_id: UUID,
        vip_epoch: int | None,
    ) -> tuple[UUID, _AutonomousDeliverJob | None]:
        """Director + routing for an already-minted turn. Caller holds chat_scope."""
        return await self._handle_vip_message_locked(
            incoming,
            vip_epoch=vip_epoch,
            turn_id=turn_id,
        )

    async def _handle_vip_message_locked(
        self,
        incoming: VipInboundMessage,
        *,
        vip_epoch: int | None,
        turn_id: UUID | None = None,
    ) -> tuple[UUID, _AutonomousDeliverJob | None]:
        bc = incoming.business_connection_id
        if bc is None or not str(bc).strip():
            if turn_id is None:
                record = await self._coordinator.begin_turn_unlocked(
                    chat_id=incoming.chat_id,
                    trigger_message_id=incoming.telegram_message_id,
                    vip_id=incoming.vip_id,
                )
                turn_id = record.id
            await self._coordinator.mark_failed(
                turn_id, error="business_connection_id is required"
            )
            raise ValueError("business_connection_id is required")

        if turn_id is None:
            # Fail-closed / legacy entry: mint then cognitive in one lock section.
            record = await self._coordinator.begin_turn_unlocked(
                chat_id=incoming.chat_id,
                trigger_message_id=incoming.telegram_message_id,
                vip_id=incoming.vip_id,
            )
            turn_id = record.id
            if vip_epoch is not None:
                self._coordinator.bind_turn_vip_epoch(
                    turn_id, incoming.chat_id, vip_epoch
                )

        # History already appended at inbound (early) so cancelled rounds still
        # join the open burst. Sandbox skips are handled there too.

        # Coalesce open VIP burst into turn text so a superseding turn answers
        # all unanswered VIP lines in this round (not only the latest message).
        turn_text = await self._coalesce_open_vip_turn_text(
            incoming.chat_id, fallback=incoming.text
        )

        turn_ctx = IncomingTurn(
            turn_id=turn_id,
            chat_id=incoming.chat_id,
            vip_id=incoming.vip_id,
            text=turn_text,
            telegram_message_id=incoming.telegram_message_id,
            business_connection_id=str(bc).strip(),
        )

        try:
            decision = await self._director.handle_turn(turn_ctx)
        except TurnSupersededError:
            logger.info(
                "turn_cancelled_mid_pipeline",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            return turn_id, None
        except Exception as exc:
            # Terminal latch: no-ops if already superseded while Director ran
            # (should not happen under full chat_scope; still safe).
            # Typed cognitive failures: mark failed + notify owner, do NOT re-raise
            # (avoids business_handler_error double-log; VIP gets no send).
            if isinstance(exc, AnalystSchemaInvalidError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="analista_schema_invalido",
                    notify_event="owner_notify_failed_after_analyst_schema_invalid",
                )
                logger.warning(
                    "director_failed_typed",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                        "error": "analista_schema_invalido",
                    },
                )
                return turn_id, None
            if isinstance(exc, EvaluatorSchemaInvalidError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="evaluador_schema_invalido",
                    notify_event="owner_notify_failed_after_evaluator_schema_invalid",
                )
                logger.warning(
                    "director_failed_typed",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                        "error": "evaluador_schema_invalido",
                    },
                )
                return turn_id, None
            if isinstance(exc, ContextExceedsLimitError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="contexto_excede_limite",
                    notify_event="owner_notify_failed_after_context_exceeds_limit",
                )
                logger.warning(
                    "director_failed_typed",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                        "error": "contexto_excede_limite",
                    },
                )
                return turn_id, None
            if isinstance(exc, GeneratorEmptyOutputError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="generador_salida_vacia",
                    notify_event="owner_notify_failed_after_generator_empty_output",
                )
                logger.warning(
                    "director_failed_typed",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                        "error": "generador_salida_vacia",
                    },
                )
                return turn_id, None
            await self._coordinator.mark_failed(turn_id, error=str(exc))
            logger.exception(
                "director_failed",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            raise

        # Route decision + transitions: owner/VIP cancel may raise on status_sink
        # when the Director stub never polled mid-pipeline (A2 clean abort).
        try:
            return await self._apply_decision_after_director(
                decision,
                turn_id=turn_id,
                turn_ctx=turn_ctx,
                incoming=incoming,
                vip_epoch=vip_epoch,
            )
        except TurnSupersededError:
            logger.info(
                "turn_cancelled_post_director",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            return turn_id, None

    async def _apply_decision_after_director(
        self,
        decision: Decision,
        *,
        turn_id: UUID,
        turn_ctx: IncomingTurn,
        incoming: VipInboundMessage,
        vip_epoch: int | None,
    ) -> tuple[UUID, _AutonomousDeliverJob | None]:
        """Apply Director decision; may raise TurnSupersededError via status_sink."""
        # Total cancel: newer VIP message while this turn was running (even if
        # the Director port is a stub that never hits status_sink transitions).
        if vip_epoch is not None and not self._coordinator.is_vip_epoch_current(
            incoming.chat_id, vip_epoch
        ):
            await self._coordinator.supersede_chat(
                incoming.chat_id,
                reason="new_message",
                superseded_by=None,
            )
            logger.info(
                "turn_cancelled_stale_epoch_post_director",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": incoming.chat_id,
                    "vip_epoch": vip_epoch,
                    "current_epoch": self._coordinator.current_vip_epoch(
                        incoming.chat_id
                    ),
                },
            )
            return turn_id, None

        # Post-Director liveness check (defense in depth vs zombie pipeline).
        live = await self._coordinator.get_turn(turn_id)
        if live is None or is_turn_status_terminal(live.status):
            logger.info(
                "orchestrator_aborted_terminal",
                extra={
                    "turn_id": str(turn_id),
                    "status": None if live is None else live.status,
                },
            )
            return turn_id, None

        if decision.action == "approve":
            await self._coordinator.transition(
                turn_id, TurnStatus.PENDING_APPROVAL
            )
            await self._admin.send_draft_for_approval(
                turn_ctx, decision, turn_id
            )
            # CRITICAL: never call behavior.deliver here (L2 / R1)
        elif decision.action == "consult_doctrine":
            if (
                turn_ctx.vip_id is None
                and self._sandbox_active(incoming.chat_id)
            ):
                demoted = decision.model_copy(
                    update={
                        "action": "approve",
                        "reason": "sandbox_no_vip_doctrine",
                    }
                )
                await self._coordinator.transition(
                    turn_id, TurnStatus.PENDING_APPROVAL
                )
                await self._admin.send_draft_for_approval(
                    turn_ctx, demoted, turn_id
                )
                logger.info(
                    "sandbox_consult_doctrine_demoted",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": incoming.chat_id,
                    },
                )
            elif not self._feature_gray_zone_enabled:
                raise RuntimeError(
                    "consult_doctrine action returned but gray zone feature is disabled"
                )
            elif self._gray_zone is None:
                raise RuntimeError(
                    "consult_doctrine action returned but GrayZoneService is not injected"
                )
            elif turn_ctx.vip_id is None:
                raise RuntimeError(
                    "consult_doctrine requires vip_id but turn has None"
                )
            else:
                # Create query + notify BEFORE transitioning to GRAY_ZONE so
                # a failure does not leave the turn stuck in gray_zone (BUG-3).
                query = await self._gray_zone.create_query(
                    vip_id=turn_ctx.vip_id,
                    turn_id=turn_id,
                    question=turn_ctx.text,
                    draft=decision.draft_text or "",
                )
                await self._admin.send_doctrine_query(
                    turn_ctx, decision, turn_id, query
                )
                await self._coordinator.transition(
                    turn_id, TurnStatus.GRAY_ZONE
                )
                logger.info(
                    "consult_doctrine_completed",
                    extra={
                        "turn_id": str(turn_id),
                        "vip_id": str(turn_ctx.vip_id),
                        "query_id": str(query.id)
                        if hasattr(query, "id")
                        else None,
                    },
                )
                # CRITICAL: never call behavior.deliver — VIP is frozen
        elif decision.action == "escalate":
            await self._coordinator.transition(turn_id, TurnStatus.ESCALATED)
            await self._admin.notify_escalation(turn_ctx, decision, turn_id)
        elif decision.action == "send":
            job = await self._prepare_autonomous_send(
                turn_id=turn_id,
                turn_ctx=turn_ctx,
                decision=decision,
                incoming=incoming,
            )
            if job is not None:
                return turn_id, job
        else:
            logger.error(
                "unexpected_f2_action",
                extra={
                    "turn_id": str(turn_id),
                    "action": decision.action,
                    "chat_id": incoming.chat_id,
                },
            )
            await self._coordinator.mark_failed(
                turn_id, error=f"unexpected F2 action: {decision.action!r}"
            )
            raise ValueError(f"unexpected F2 action: {decision.action!r}")

        logger.info(
            "vip_message_handled",
            extra={
                "turn_id": str(turn_id),
                "chat_id": incoming.chat_id,
                "action": decision.action,
            },
        )
        return turn_id, None

    async def _prepare_autonomous_send(
        self,
        *,
        turn_id: UUID,
        turn_ctx: IncomingTurn,
        decision: Decision,
        incoming: VipInboundMessage,
    ) -> _AutonomousDeliverJob | None:
        """Gate AMS + frozen/empty; return deliver job or complete under lock."""
        if self._autonomous_mode is None:
            logger.error(
                "autonomous_not_wired",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": incoming.chat_id,
                },
            )
            await self._coordinator.mark_failed(
                turn_id, error="autonomous_not_wired"
            )
            return None

        enabled = await self._autonomous_mode.is_autonomous_enabled(
            incoming.vip_id
        )
        if not enabled:
            logger.info(
                "autonomous_disabled_for_vip",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": incoming.chat_id,
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            # Demote send → approve with explicit reason (not autonomous_ok).
            demoted = decision.model_copy(
                update={
                    "action": "approve",
                    "reason": "autonomous_mode_disabled",
                }
            )
            await self._coordinator.transition(
                turn_id, TurnStatus.PENDING_APPROVAL
            )
            await self._admin.send_draft_for_approval(
                turn_ctx, demoted, turn_id
            )
            return None

        if await self._is_vip_frozen(incoming.vip_id):
            logger.info(
                "autonomous_vip_frozen",
                extra={
                    "turn_id": str(turn_id),
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            await self._coordinator.mark_failed(turn_id, error="vip_frozen")
            await self._safe_notify_info(
                f"Turn {turn_id} failed: vip_frozen",
                chat_id=incoming.chat_id,
                event="owner_notify_failed_after_vip_frozen",
                turn_id=str(turn_id),
            )
            return None

        draft = (decision.draft_text or "").strip()
        if not draft:
            logger.info(
                "autonomous_empty_draft",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            await self._coordinator.mark_failed(turn_id, error="empty_draft")
            await self._safe_notify_info(
                f"Turn {turn_id} failed: empty_draft",
                chat_id=incoming.chat_id,
                event="owner_notify_failed_after_empty_draft",
                turn_id=str(turn_id),
            )
            return None

        if self._behavior is None:
            logger.error(
                "autonomous_behavior_not_wired",
                extra={"turn_id": str(turn_id)},
            )
            await self._coordinator.mark_failed(
                turn_id, error="autonomous_behavior_not_wired"
            )
            return None

        # is_frozen=False: prepare only builds a job when VIP is not frozen.
        # Engine hard-check of is_frozen is defense-in-depth; orch re-checks
        # after lock release before deliver.
        advanced = self._feature_advanced_behavior
        mode = self._effective_delivery_mode(incoming.chat_id)
        if mode == "fake_delivery":
            logger.info(
                "delivery_mode_fake",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
        ctx = DeliveryContext(
            chat_id=incoming.chat_id,
            business_connection_id=str(turn_ctx.business_connection_id).strip(),
            vip_id=incoming.vip_id,
            telegram_message_id=incoming.telegram_message_id,
            mode=mode,
            is_frozen=False,
            skip_initial_delay=True,
            allow_split=advanced,
            allow_human_quirks=advanced,
            split_chars=4096,
        )
        return _AutonomousDeliverJob(text=draft, ctx=ctx, decision=decision)

    async def _is_vip_frozen(self, vip_id: UUID | None) -> bool:
        """True if vip_store says frozen_until > now(UTC). Missing store/id → False."""
        if self._vip_store is None or vip_id is None:
            return False
        vip = await self._vip_store.get_by_id(vip_id)
        if vip is None or vip.frozen_until is None:
            return False
        now = datetime.now(UTC)
        frozen = vip.frozen_until
        if frozen.tzinfo is None:
            frozen = frozen.replace(tzinfo=UTC)
        return frozen > now

    async def _finalize_autonomous_delivery(
        self,
        turn_id: UUID,
        chat_id: int,
        result: DeliveryResult,
        text: str,
    ) -> bool:
        """Post-deliver terminal check under chat lock (Admin I.5 parity, no approval).

        Returns True only when the turn was transitioned to DELIVERED.
        Not a SQL CAS / claim token — single-process lock + terminal latch.
        """
        turn_after = await self._coordinator.get_turn(turn_id)
        if turn_after is None or is_turn_status_terminal(turn_after.status):
            logger.info(
                "autonomous_aborted_terminal_after_deliver",
                extra={
                    "turn_id": str(turn_id),
                    "status": None if turn_after is None else turn_after.status,
                    "deliver_success": result.success,
                },
            )
            return False

        if result.success:
            await self._coordinator.transition(turn_id, TurnStatus.DELIVERED)
            if self._traces is not None:
                await self._traces.set_delivery_result(
                    turn_id, result.to_trace_dict()
                )
            # H7.2: owner history for Diana outbound (role maps to autor=dueña).
            # Skip durable history when sandbox is active (should_persist false).
            # Multi-segment: one owner row per message_id when texts align.
            if (
                self._sandbox is not None
                and not self._sandbox.should_persist(chat_id)  # type: ignore[union-attr]
            ):
                logger.info(
                    "owner_history_skipped_sandbox",
                    extra={"turn_id": str(turn_id), "chat_id": chat_id},
                )
            else:
                await append_owner_delivery_history(
                    self._history,
                    chat_id,
                    result=result,
                    fallback_text=text,
                    turn_id=turn_id,
                )
            logger.info(
                "autonomous_delivered",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return True

        if result.cancelled:
            await self._coordinator.mark_failed(
                turn_id, error=result.error or "delivery_cancelled"
            )
            if self._traces is not None:
                await self._traces.set_delivery_result(
                    turn_id, result.to_trace_dict()
                )
            logger.info(
                "autonomous_deliver_cancelled",
                extra={
                    "turn_id": str(turn_id),
                    "error": result.error,
                },
            )
            return False

        # Permanent deliver failure (I.5).
        await self._coordinator.mark_failed(
            turn_id, error=result.error or "delivery_failed"
        )
        await self._safe_notify_info(
            f"Turn {turn_id} failed: delivery_failed ({result.error})",
            chat_id=chat_id,
            event="owner_notify_failed_after_autonomous_deliver_fail",
            turn_id=str(turn_id),
        )
        if self._traces is not None:
            await self._traces.set_delivery_result(
                turn_id, result.to_trace_dict()
            )
        logger.info(
            "autonomous_deliver_failed",
            extra={"turn_id": str(turn_id), "error": result.error},
        )
        return False
