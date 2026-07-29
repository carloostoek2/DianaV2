"""BehaviorEngine — sequences human-like delivery; never decides or calls LLM.

Answers only: how is the already-approved message acted?

English ↔ Anexo I:
- mode supervised|autonomous|fake_delivery ↔ supervisado|autonomo|fake_delivery
- DeliveryResult.success ↔ ok
- Pre-send TurnStatusReader gate ↔ I.4 supersede abort
- Bounded TransientSendError retries ↔ I.4 / REQ-NFR-04

May apply mechanical human quirks (extra pause, natural split, typo+correction)
under FEATURE_ADVANCED_BEHAVIOR dual gate. Never uses LLM. Never imports
cognitive/aiogram.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any
from uuid import UUID, uuid4

from diana.application.ports import DeliveryRecord, PendingDeliveryStore
from diana.behavior.ports import (
    Clock,
    DelayPolicy,
    DeliveryContext,
    DeliveryResult,
    TelegramActuatorPort,
    TransientSendError,
    TurnStatusReader,
)
from diana.behavior.quirks import QuirkKind, apply_typo, natural_split_text, pick_quirk
from diana.behavior.split import split_text
from diana.behavior.timer_manager import TimerManager

logger = logging.getLogger("diana.behavior")

# Local strings only — no cognitive import (L3).
_TERMINAL_SEND_ABORT: frozenset[str] = frozenset(
    {"superseded", "delivered", "failed", "escalated"}
)
# C4: pause quirk = fixed extra sleep (no text rewrite).
_QUIRK_EXTRA_PAUSE_SECONDS = 0.03


class BehaviorEngine:
    """Act messages via ports: delay → read → typing → send; cancel-aware."""

    def __init__(
        self,
        actuator: TelegramActuatorPort,
        deliveries: PendingDeliveryStore,
        *,
        clock: Clock,
        delay_policy: DelayPolicy,
        timers: TimerManager | None = None,
        turn_status: TurnStatusReader | None = None,
        max_send_attempts: int = 3,
        retry_backoff_seconds: float = 0.05,
        feature_advanced_behavior: bool = False,
        quirk_probability: float = 0.0,
        quirk_force: str | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._actuator = actuator
        self._deliveries = deliveries
        self._clock = clock
        self._delay = delay_policy
        self._timers = timers or TimerManager()
        self._turn_status = turn_status
        self._max_send_attempts = max(1, max_send_attempts)
        self._retry_backoff_seconds = retry_backoff_seconds
        self._advanced = bool(feature_advanced_behavior)
        self._quirk_probability = max(0.0, min(1.0, float(quirk_probability)))
        self._quirk_force = quirk_force
        self._rng = rng if rng is not None else random.Random()

    async def deliver(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
        decision: Any | None = None,
    ) -> DeliveryResult:
        """Run the delivery sequence for ``texts`` toward ``ctx.chat_id``.

        ``turn_id`` is required for pending_deliveries FK and cancel scope.
        ``decision`` is stored as a dump for reconstructability only.

        Caller-supplied multi-text keeps single typing (no inter-gap). When
        dual-gate split expands a long text, inter-message delay+typing applies
        between expanded segments (SPEC §6.6 / A2).
        """
        prepared, inter_gap, quirk = self._prepare_delivery(list(texts), ctx)
        return await self._deliver_core(
            prepared,
            ctx,
            turn_id,
            decision=decision,
            inter_message_gap=inter_gap,
            quirk=quirk,
        )

    async def deliver_with_sequence(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
        decision: Any | None = None,
    ) -> DeliveryResult:
        """Multi-text delivery with inter-message delay+typing (C5 / REQ-HUM-05).

        Always uses inter-message gaps. Honors ``is_frozen`` and advanced dual
        gates. Not part of ``BehaviorDeliverer`` protocol — concrete API only.
        """
        prepared, _split_gap, quirk = self._prepare_delivery(list(texts), ctx)
        return await self._deliver_core(
            prepared,
            ctx,
            turn_id,
            decision=decision,
            inter_message_gap=True,
            quirk=quirk,
        )

    async def _deliver_core(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
        *,
        decision: Any | None = None,
        inter_message_gap: bool = False,
        quirk: QuirkKind | None = None,
    ) -> DeliveryResult:
        bc = (ctx.business_connection_id or "").strip()
        if not bc:
            return DeliveryResult(
                success=False,
                error="business_connection_id is required",
            )

        # C1: frozen snapshot at entry — no insert, no send, no fake success.
        frozen = self._frozen_abort(ctx)
        if frozen is not None:
            return frozen

        if not texts:
            return DeliveryResult(success=False, error="empty_texts")

        delivery_id = uuid4()
        decision_dump: dict = {}
        if decision is not None:
            if hasattr(decision, "model_dump"):
                decision_dump = decision.model_dump(mode="json")
            elif isinstance(decision, dict):
                decision_dump = dict(decision)

        record = DeliveryRecord(
            id=delivery_id,
            chat_id=ctx.chat_id,
            business_connection_id=bc,
            texts=list(texts),
            decision=decision_dump,
            scheduled_at=self._clock.now(),
            status="pending",
            turn_id=turn_id,
            vip_id=ctx.vip_id,
        )
        await self._deliveries.insert_pending(record)

        # Register before any await so cancel_pending can interrupt immediately.
        current = asyncio.current_task()
        if current is not None:
            await self._timers.register(ctx.chat_id, turn_id, current)

        try:
            if not await self._deliveries.update_status(delivery_id, "delivering"):
                return DeliveryResult(
                    success=False, cancelled=True, error="cancelled_before_start"
                )

            if ctx.skip_initial_delay:
                initial = 0.0
            else:
                initial = self._delay.initial_delay_seconds(ctx.mode)
            await self._clock.sleep(initial)

            if quirk == "pause":
                logger.info(
                    "delivery_quirk_pause",
                    extra={
                        "chat_id": ctx.chat_id,
                        "seconds": _QUIRK_EXTRA_PAUSE_SECONDS,
                    },
                )
                await self._clock.sleep(_QUIRK_EXTRA_PAUSE_SECONDS)

            if ctx.mode == "fake_delivery":
                return await self._deliver_fake(
                    delivery_id=delivery_id,
                    turn_id=turn_id,
                    ctx=ctx,
                    initial=initial,
                )

            if ctx.telegram_message_id is not None:
                await self._actuator.read_business_message(
                    ctx.chat_id,
                    ctx.telegram_message_id,
                    business_connection_id=bc,
                )

            typing_secs = 0.0
            message_ids: list[int] = []
            for index, text in enumerate(texts):
                if index == 0 or inter_message_gap:
                    if index > 0 and inter_message_gap:
                        await self._clock.sleep(initial)
                    typing_secs = self._delay.typing_duration_seconds(text)
                    await self._actuator.send_chat_action(
                        ctx.chat_id,
                        "typing",
                        business_connection_id=bc,
                    )
                    await self._clock.sleep(typing_secs)

                frozen_mid = await self._frozen_abort_pending(
                    delivery_id=delivery_id,
                    ctx=ctx,
                    initial=initial,
                    typing_secs=typing_secs,
                    message_ids=message_ids,
                )
                if frozen_mid is not None:
                    return frozen_mid

                abort = await self._presend_abort_if_not_live(
                    delivery_id=delivery_id,
                    turn_id=turn_id,
                    ctx=ctx,
                    initial=initial,
                    typing_secs=typing_secs,
                    message_ids=message_ids,
                )
                if abort is not None:
                    return abort

                send_result = await self._send_with_retries(
                    delivery_id=delivery_id,
                    turn_id=turn_id,
                    ctx=ctx,
                    bc=bc,
                    text=text,
                    initial=initial,
                    typing_secs=typing_secs,
                    message_ids=message_ids,
                )
                if send_result is not None:
                    return send_result
                # last successful mid appended inside _send_with_retries

            # Never overwrite cancelled/expired with done (CAS).
            applied = await self._deliveries.update_status(delivery_id, "done")
            if not applied:
                logger.info(
                    "delivery_done_rejected",
                    extra={"turn_id": str(turn_id), "chat_id": ctx.chat_id},
                )
                return DeliveryResult(
                    success=False,
                    cancelled=True,
                    message_ids=message_ids,
                    actual_delay_seconds=initial,
                    typing_duration_seconds=typing_secs,
                    error="status_rejected",
                )

            logger.info(
                "delivery_done",
                extra={"turn_id": str(turn_id), "chat_id": ctx.chat_id},
            )
            return DeliveryResult(
                success=True,
                message_ids=message_ids,
                texts=list(texts),
                actual_delay_seconds=initial,
                typing_duration_seconds=typing_secs,
            )
        except asyncio.CancelledError:
            await self._safe_mark(delivery_id, "cancelled")
            logger.info(
                "delivery_cancelled",
                extra={"turn_id": str(turn_id), "chat_id": ctx.chat_id},
            )
            return DeliveryResult(success=False, cancelled=True, error="cancelled")
        except Exception as exc:  # noqa: BLE001 — surface as delivery failure
            await self._safe_mark(delivery_id, "error")
            return DeliveryResult(success=False, error=str(exc))

    def _prepare_delivery(
        self, texts: list[str], ctx: DeliveryContext
    ) -> tuple[list[str], bool, QuirkKind | None]:
        """Normalize, length-split, then apply at most one selected quirk.

        Returns ``(texts, inter_message_gap, resolved_quirk)``.
        Inter-gap is True when length-split, natural_split, or typo expansion
        produced multi-segment delivery.
        """
        prepared, inter_gap = self._prepare_texts(texts, ctx)
        quirk = self._select_quirk(ctx)
        if quirk is None or not prepared:
            return prepared, inter_gap, None

        if quirk == "natural_split":
            new_prepared, did = self._apply_natural_split_quirk(prepared)
            if did:
                logger.info(
                    "delivery_quirk_natural_split",
                    extra={"chat_id": ctx.chat_id, "segments": len(new_prepared)},
                )
                return new_prepared, True, "natural_split"
            quirk = "pause"

        if quirk == "typo_correct":
            applied = self._apply_typo_quirk(prepared)
            if applied is not None:
                logger.info(
                    "delivery_quirk_typo",
                    extra={"chat_id": ctx.chat_id},
                )
                return applied, True, "typo_correct"
            quirk = "pause"

        # pause (selected or fallback) — applied as sleep in _deliver_core
        return prepared, inter_gap, "pause" if quirk == "pause" else quirk

    def _select_quirk(self, ctx: DeliveryContext) -> QuirkKind | None:
        """Dual gate: advanced flag ∧ allow_human_quirks; then probability/force."""
        if not (self._advanced and ctx.allow_human_quirks):
            return None
        return pick_quirk(
            self._rng,
            self._quirk_probability,
            force=self._quirk_force,
        )

    def _apply_natural_split_quirk(
        self, texts: list[str]
    ) -> tuple[list[str], bool]:
        """Split first eligible segment on sentence boundaries."""
        expanded: list[str] = []
        did = False
        for t in texts:
            if not did:
                parts = natural_split_text(t)
                if len(parts) > 1:
                    expanded.extend(parts)
                    did = True
                    continue
            expanded.append(t)
        return expanded, did

    def _apply_typo_quirk(self, texts: list[str]) -> list[str] | None:
        """Rewrite first bubble with mild typo + insert ``*{word}`` correction."""
        if not texts:
            return None
        result = apply_typo(texts[0], self._rng)
        if result is None:
            return None
        typoed, correction = result
        return [typoed, correction, *texts[1:]]

    def _prepare_texts(
        self, texts: list[str], ctx: DeliveryContext
    ) -> tuple[list[str], bool]:
        """Normalize + optional dual-gate length split. Returns (texts, inter_gap).

        Inter-gap is True only when length-split expansion produced multi-segment
        (A2). Caller multi-text without expand stays False.
        """
        normalized = [t for t in (x.strip() if isinstance(x, str) else x for x in texts) if t]
        if not (self._advanced and ctx.allow_split):
            return normalized, False

        expanded: list[str] = []
        did_expand = False
        for t in normalized:
            if len(t) > ctx.split_chars:
                parts = split_text(t, ctx.split_chars)
                if len(parts) > 1:
                    did_expand = True
                expanded.extend(parts if parts else [t])
            else:
                expanded.append(t)

        if did_expand:
            logger.info(
                "delivery_split",
                extra={
                    "chat_id": ctx.chat_id,
                    "segments": len(expanded),
                    "split_chars": ctx.split_chars,
                },
            )
        return expanded, did_expand

    def _frozen_abort(self, ctx: DeliveryContext) -> DeliveryResult | None:
        """C1: entry freeze hard-check (no pending row yet)."""
        if not ctx.is_frozen:
            return None
        logger.info(
            "delivery_frozen",
            extra={"chat_id": ctx.chat_id, "phase": "entry"},
        )
        return DeliveryResult(
            success=False,
            cancelled=True,
            error="vip_frozen",
        )

    async def _frozen_abort_pending(
        self,
        *,
        delivery_id: UUID,
        ctx: DeliveryContext,
        initial: float,
        typing_secs: float,
        message_ids: list[int],
    ) -> DeliveryResult | None:
        """C1: re-check freeze before real/fake completion; mark cancelled if pending."""
        if not ctx.is_frozen:
            return None
        await self._safe_mark(delivery_id, "cancelled")
        logger.info(
            "delivery_frozen",
            extra={"chat_id": ctx.chat_id, "phase": "presend"},
        )
        return DeliveryResult(
            success=False,
            cancelled=True,
            message_ids=list(message_ids),
            actual_delay_seconds=initial,
            typing_duration_seconds=typing_secs,
            error="vip_frozen",
        )

    async def _deliver_fake(
        self,
        *,
        delivery_id: UUID,
        turn_id: UUID,
        ctx: DeliveryContext,
        initial: float,
    ) -> DeliveryResult:
        """Record-only path: no actuator I/O; still honors freeze + pre-send live check."""
        frozen = await self._frozen_abort_pending(
            delivery_id=delivery_id,
            ctx=ctx,
            initial=initial,
            typing_secs=0.0,
            message_ids=[],
        )
        if frozen is not None:
            return frozen

        abort = await self._presend_abort_if_not_live(
            delivery_id=delivery_id,
            turn_id=turn_id,
            ctx=ctx,
            initial=initial,
            typing_secs=0.0,
            message_ids=[],
        )
        if abort is not None:
            return abort

        applied = await self._deliveries.update_status(delivery_id, "done")
        if not applied:
            return DeliveryResult(
                success=False,
                cancelled=True,
                actual_delay_seconds=initial,
                error="status_rejected",
            )
        logger.info(
            "delivery_fake",
            extra={"turn_id": str(turn_id), "chat_id": ctx.chat_id},
        )
        return DeliveryResult(
            success=True,
            message_ids=[],
            actual_delay_seconds=initial,
            typing_duration_seconds=0.0,
        )

    async def _presend_abort_if_not_live(
        self,
        *,
        delivery_id: UUID,
        turn_id: UUID,
        ctx: DeliveryContext,
        initial: float,
        typing_secs: float,
        message_ids: list[int],
    ) -> DeliveryResult | None:
        """I.4: abort without send when turn is missing or terminal.

        When no reader is injected (unit fixtures), treat as always live.
        Production composition MUST inject a TurnStatusReader.
        """
        if self._turn_status is None:
            return None

        status = await self._turn_status.get_status(turn_id)
        if status is not None and status not in _TERMINAL_SEND_ABORT:
            return None

        await self._safe_mark(delivery_id, "cancelled")
        error = (
            "superseded_before_send"
            if status is None or status == "superseded"
            else f"turn_not_live:{status}"
        )
        logger.info(
            "delivery_presend_abort",
            extra={
                "turn_id": str(turn_id),
                "chat_id": ctx.chat_id,
                "status": status,
            },
        )
        return DeliveryResult(
            success=False,
            cancelled=True,
            message_ids=list(message_ids),
            actual_delay_seconds=initial,
            typing_duration_seconds=typing_secs,
            error=error,
        )

    async def _send_with_retries(
        self,
        *,
        delivery_id: UUID,
        turn_id: UUID,
        ctx: DeliveryContext,
        bc: str,
        text: str,
        initial: float,
        typing_secs: float,
        message_ids: list[int],
    ) -> DeliveryResult | None:
        """Attempt send with bounded TransientSendError retries. None = success."""
        last_error: str | None = None
        for attempt in range(1, self._max_send_attempts + 1):
            try:
                mid = await self._actuator.send_message(
                    ctx.chat_id,
                    text,
                    business_connection_id=bc,
                )
                message_ids.append(mid)
                return None
            except asyncio.CancelledError:
                raise
            except TransientSendError as exc:
                last_error = str(exc) or "transient_send_error"
                if attempt >= self._max_send_attempts:
                    break
                logger.info(
                    "delivery_send_retry",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": ctx.chat_id,
                        "attempt": attempt,
                    },
                )
                await self._clock.sleep(self._retry_backoff_seconds)
            except Exception as exc:  # permanent — no retry
                await self._safe_mark(delivery_id, "error")
                return DeliveryResult(
                    success=False,
                    message_ids=list(message_ids),
                    actual_delay_seconds=initial,
                    typing_duration_seconds=typing_secs,
                    error=str(exc),
                )

        await self._safe_mark(delivery_id, "error")
        return DeliveryResult(
            success=False,
            message_ids=list(message_ids),
            actual_delay_seconds=initial,
            typing_duration_seconds=typing_secs,
            error=last_error or "send_retries_exhausted",
        )

    async def cancel_pending(
        self, chat_id: int, reason: str = "new_message"
    ) -> None:
        """Cancel in-flight tasks for chat_id + mark pending/delivering cancelled.

        Idempotent: safe to call when nothing is pending.
        """
        await self._timers.cancel_chat(chat_id)
        n = await self._deliveries.cancel_for_chat(chat_id)
        logger.info(
            "cancel_pending",
            extra={"chat_id": chat_id, "rows_cancelled": n, "reason": reason},
        )

    async def _safe_mark(self, delivery_id: UUID, status: str) -> None:
        try:
            await self._deliveries.update_status(delivery_id, status)
        except KeyError:
            return
