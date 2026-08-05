"""AdminService — owner approval queue (domain API, no aiogram types)."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any
from uuid import UUID, uuid4

from diana.application.ports import (
    ApprovalRecord,
    BehaviorDeliverer,
    DeliveryContext,
    DeliveryMode,
    DeliveryResult,
    DeliveryResultWriter,
    DoctrineNotification,
    DraftNotification,
    EscalationNotification,
    EscalationStore,
    GrayZoneQueryView,
    MessageHistoryWriter,
    OwnerNotifierPort,
    PendingApprovalStore,
    TurnStore,
    VipStore,
)
from diana.application.draft_variants import ensure_versions
from diana.application.escalation_labels import tipo_from_reason
from diana.application.owner_history import append_owner_delivery_history
from diana.application.staging_service import StagingService
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.models import (
    Decision,
    IncomingTurn,
    TurnStatus,
    is_turn_status_terminal,
)

logger = logging.getLogger("diana.application")

# ROADMAP 5.7: durable audit trail of escalations as a plain-text rotating log.
# DB stores structured escalation rows (escalations table) and the owner
# receives a Telegram DM, but operators also want a grep-friendly file for
# post-incident review. The handler is attached lazily on first escalation
# so importing this module is side-effect-free in tests.
_ESCALATION_LOG_PATH = os.environ.get(
    "DIANA_ESCALATION_LOG_PATH", "/var/log/diana/escalations.log"
)
_ESCALATION_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_ESCALATION_LOG_BACKUP_COUNT = 5
_escalation_file_handler_attached = False


def _ensure_escalation_file_handler() -> None:
    """Attach a RotatingFileHandler to the escalation logger (once per process)."""
    global _escalation_file_handler_attached
    if _escalation_file_handler_attached:
        return
    escalation_logger = logging.getLogger("diana.escalations")
    # Skip if the root config or a prior attach already provided one.
    if any(isinstance(h, RotatingFileHandler) for h in escalation_logger.handlers):
        _escalation_file_handler_attached = True
        return
    try:
        # Ensure the parent directory exists; if it can't (e.g. sandbox),
        # the handler is silently skipped — DB and Telegram paths still work.
        os.makedirs(os.path.dirname(_ESCALATION_LOG_PATH), exist_ok=True)
        handler = RotatingFileHandler(
            _ESCALATION_LOG_PATH,
            maxBytes=_ESCALATION_LOG_MAX_BYTES,
            backupCount=_ESCALATION_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        escalation_logger.addHandler(handler)
        escalation_logger.setLevel(logging.INFO)
        _escalation_file_handler_attached = True
    except OSError:
        # Filesystem not writable (e.g. tests, container without /var/log).
        # Fail-soft: the in-process logger and DB/DM paths remain functional.
        pass


class OwnerAuthError(PermissionError):
    """Raised when a non-owner actor attempts an owner-only admin action."""


def _eval_summary(decision: Decision) -> str:
    """Display-only summary string; never fed back into Decider."""
    e = decision.evaluation
    return (
        f"nat={e.naturalness:.2f} prec={e.precision:.2f} "
        f"doc={e.doctrine:.2f} con={e.consistency:.2f} "
        f"saf={e.safety:.2f} cov={e.coverage:.2f} emp={e.empathy:.2f}"
    )


class AdminService:
    """Owner-facing draft queue and owner resolve path that may call Behavior.deliver.

    Autonomous TurnOrchestrator send path may also call Behavior.deliver when
    AMS L1/L2 enablement allows it (feature flag + global/VIP gate).
    """

    def __init__(
        self,
        *,
        notifier: OwnerNotifierPort,
        approvals: PendingApprovalStore,
        escalations: EscalationStore,
        coordinator: TurnCoordinator,
        behavior: BehaviorDeliverer,
        traces: DeliveryResultWriter,
        turns: TurnStore,
        owner_telegram_id: int,
        delivery_mode: DeliveryMode = "supervised",
        feature_advanced_behavior: bool = False,
        vip_store: VipStore | None = None,
        fp_marks: Any | None = None,
        sandbox: Any | None = None,
        staging: StagingService | None = None,
        history: MessageHistoryWriter | None = None,
    ) -> None:
        self._notifier = notifier
        self._approvals = approvals
        self._escalations = escalations
        self._coordinator = coordinator
        self._behavior = behavior
        self._traces = traces
        self._turns = turns
        self._owner_telegram_id = owner_telegram_id
        self._delivery_mode = delivery_mode
        self._feature_advanced_behavior = bool(feature_advanced_behavior)
        self._vip_store = vip_store
        self._fp_marks = fp_marks
        self._sandbox = sandbox
        self._staging = staging
        self._history = history

    def _assert_owner(self, actor_id: int | None) -> None:
        if actor_id is None or actor_id != self._owner_telegram_id:
            raise OwnerAuthError(
                f"actor_id {actor_id!r} is not the configured owner"
            )

    def _sandbox_prefix(self, chat_id: int) -> str:
        if self._sandbox is None or not self._sandbox.is_active(chat_id):
            return ""
        key = self._sandbox.get_profile(chat_id) or "?"
        return f"SANDBOX — profile: {key}"

    def _sandbox_reason(self, chat_id: int, reason: str) -> str:
        prefix = self._sandbox_prefix(chat_id)
        if not prefix:
            return reason
        return f"{prefix} | {reason}"

    def _effective_delivery_mode(self, _chat_id: int) -> DeliveryMode:
        # Sandbox must not force fake_delivery; product isolation is should_persist.
        return self._delivery_mode

    async def send_draft_for_approval(
        self,
        turn: IncomingTurn,
        decision: Decision,
        turn_id: UUID,
    ) -> None:
        bc = (turn.business_connection_id or "").strip()
        if not bc:
            raise ValueError("business_connection_id is required for approval")
        draft = decision.draft_text or ""
        eval_dict = ensure_versions(
            decision.evaluation.model_dump(mode="json"),
            draft_text=draft,
            reason=decision.reason or "",
            vip_text=turn.text,
        )
        record = ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=turn.chat_id,
            business_connection_id=bc,
            draft_text=draft,
            status="waiting",
            vip_id=turn.vip_id,
            cognitive_summary=decision.reason,
            evaluation=eval_dict,
            trigger_message_id=turn.telegram_message_id,
        )
        await self._approvals.create_waiting(record)
        reason = self._sandbox_reason(turn.chat_id, decision.reason)

        # Look up the VIP display name for the draft header.
        vip_name: str | None = None
        if self._vip_store is not None:
            if turn.vip_id is not None:
                vip_rec = await self._vip_store.get_by_id(turn.vip_id)
            else:
                vip_rec = await self._vip_store.get_by_telegram_user_id(turn.chat_id)
            if vip_rec is not None:
                vip_name = vip_rec.display_name

        owner_mid = await self._notifier.notify_draft(
            DraftNotification(
                turn_id=turn_id,
                chat_id=turn.chat_id,
                vip_text=turn.text,
                draft_text=draft,
                reason=reason,
                vip_display_name=vip_name,
                evaluation_summary=_eval_summary(decision),
                evaluation=decision.evaluation.model_dump(mode="json"),
                business_connection_id=bc,
                reply_markup_spec={
                    "actions": ["approve", "correct", "escalate"],
                    "turn_id": str(turn_id),
                },
            )
        )
        if owner_mid is not None:
            await self._approvals.set_owner_message_id(turn_id, owner_mid)
        logger.info(
            "draft_for_approval",
            extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
        )

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        """Thin wrapper for operator/info notifications (e.g. Analyst schema fail)."""
        await self._notifier.notify_info(text, chat_id=chat_id)

    async def notify_escalation(
        self,
        turn: IncomingTurn,
        decision: Decision,
        turn_id: UUID,
    ) -> None:
        tipo = tipo_from_reason(decision.reason)
        reason = self._sandbox_reason(turn.chat_id, decision.reason)
        await self._escalations.create(
            turn_id, tipo=tipo, motivo=reason
        )
        await self._notifier.notify_escalation(
            EscalationNotification(
                turn_id=turn_id,
                chat_id=turn.chat_id,
                reason=reason,
                vip_text=turn.text,
                tipo=tipo,
                business_connection_id=turn.business_connection_id,
            )
        )
        await self._escalations.mark_notified(turn_id)
        # ROADMAP 5.7: append a one-line plain-text record to the audit log.
        _ensure_escalation_file_handler()
        logging.getLogger("diana.escalations").info(
            "turn=%s chat=%s vip_text=%r tipo=%s reason=%s",
            str(turn_id),
            turn.chat_id,
            (turn.text or "")[:200],
            tipo,
            reason,
        )
        logger.info(
            "escalation_notified",
            extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
        )

    async def send_doctrine_query(
        self,
        turn: IncomingTurn,
        decision: Decision,
        turn_id: UUID,
        query: GrayZoneQueryView,
    ) -> None:
        """Notify owner of a gray zone doctrine query (VIP frozen).

        Sends DM with the VIP's question, the draft, and reply markup
        for the owner to respond with doctrine guidance.
        Does NOT deliver to the VIP (VIP is frozen).

        Note: owner_mid is NOT persisted in F2 because the
        GrayZoneQuery model lacks an owner_message_id column. For F3/Item 4
        callback handlers, the handler looks up the open query by turn_id.
        """
        bc = (turn.business_connection_id or "").strip()
        if not bc:
            raise ValueError("business_connection_id is required for doctrine query")

        draft = decision.draft_text or ""
        query_id = query.id
        reason = self._sandbox_reason(turn.chat_id, decision.reason)

        reply_spec: dict = {
            "actions": ["respond_doctrine", "resolve_with_draft", "escalate_doctrine"],
            "turn_id": str(turn_id),
        }
        if query_id is not None:
            reply_spec["query_id"] = str(query_id)

        try:
            owner_mid = await self._notifier.notify_doctrine(
                DoctrineNotification(
                    turn_id=turn_id,
                    chat_id=turn.chat_id,
                    vip_text=turn.text,
                    draft_text=draft,
                    reason=reason,
                    evaluation_summary=_eval_summary(decision),
                    business_connection_id=bc,
                    reply_markup_spec=reply_spec,
                )
            )
        except Exception:
            logger.exception(
                "doctrine_notification_failed",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": turn.chat_id,
                    "query_id": str(query_id) if query_id else None,
                },
            )
            raise

        logger.info(
            "doctrine_query_notified",
            extra={
                "turn_id": str(turn_id),
                "chat_id": turn.chat_id,
                "query_id": str(query_id) if query_id else None,
                "owner_message_id": owner_mid,
            },
        )

    async def handle_approve(
        self,
        turn_id: UUID,
        *,
        actor_id: int | None = None,
    ) -> DeliveryResult | None:
        self._assert_owner(actor_id)
        return await self._resolve_and_deliver(turn_id, corrected_text=None)

    async def handle_correct(
        self,
        turn_id: UUID,
        corrected_text: str,
        *,
        actor_id: int | None = None,
    ) -> DeliveryResult | None:
        self._assert_owner(actor_id)
        if not (corrected_text or "").strip():
            raise ValueError("corrected_text must be non-empty")
        stripped = corrected_text.strip()
        # H7.1 timing A: capture correction before claim/deliver (orphan pending OK).
        if self._staging is not None:
            turn = await self._turns.get(turn_id)
            approval = await self._approvals.get_by_turn(turn_id)
            if turn is not None and approval is not None:
                turn_text = await self._resolve_trigger_text(
                    turn.chat_id, turn.trigger_message_id
                )
                try:
                    await self._staging.save_correction(
                        turn_id,
                        original_draft=approval.draft_text,
                        corrected_text=stripped,
                        context={
                            "chat_id": turn.chat_id,
                            "turn_text": turn_text,
                        },
                        chat_id=turn.chat_id,
                        channel_type=turn.channel_type,
                    )
                except Exception:
                    logger.exception(
                        "staging_save_correction_failed",
                        extra={"turn_id": str(turn_id)},
                    )
        return await self._resolve_and_deliver(turn_id, corrected_text=stripped)

    async def _resolve_trigger_text(
        self,
        chat_id: int,
        trigger_message_id: int | None,
    ) -> str:
        """Resolve VIP trigger text from history by telegram_message_id (H7)."""
        if self._history is None or trigger_message_id is None:
            return ""
        try:
            recent = await self._history.get_recent(chat_id, limit=20)
        except Exception:
            logger.exception(
                "owner_history_trigger_lookup_failed",
                extra={"chat_id": chat_id, "trigger_message_id": trigger_message_id},
            )
            return ""
        matches: list[dict[str, Any]] = []
        for row in recent:
            if not isinstance(row, dict):
                continue
            if row.get("telegram_message_id") == trigger_message_id:
                matches.append(row)
        if not matches:
            return ""
        for row in matches:
            if row.get("role") == "vip":
                return str(row.get("text") or "")
        return str(matches[0].get("text") or "")

    async def is_pending_approval(self, turn_id: UUID) -> bool:
        """True when turn is non-terminal and has a waiting approval."""
        turn = await self._turns.get(turn_id)
        if turn is None or is_turn_status_terminal(turn.status):
            return False
        approval = await self._approvals.get_by_turn(turn_id)
        return approval is not None and approval.status == "waiting"

    async def mark_false_positive(
        self,
        turn_id: UUID,
        *,
        actor_id: int | None = None,
    ) -> bool:
        """Record owner mark that an escalation was a false positive (metrics).

        Thin entry point — no Telegram UI required. Returns False when the
        mark store is not wired.
        """
        self._assert_owner(actor_id)
        if self._fp_marks is None:
            logger.info(
                "mark_false_positive_no_store",
                extra={"turn_id": str(turn_id)},
            )
            return False
        await self._fp_marks.mark(turn_id)
        logger.info(
            "false_positive_marked",
            extra={"turn_id": str(turn_id)},
        )
        return True

    async def handle_owner_escalate(
        self,
        turn_id: UUID,
        *,
        actor_id: int | None = None,
    ) -> bool:
        """Owner discard/escalate: cancel waiting approval; never deliver.

        Returns True when the turn was transitioned to escalated; False on no-op.
        """
        self._assert_owner(actor_id)
        turn = await self._turns.get(turn_id)
        if turn is None:
            logger.info(
                "owner_escalate_missing_turn", extra={"turn_id": str(turn_id)}
            )
            return False
        chat_id = turn.chat_id

        async with self._coordinator.chat_scope(chat_id):
            turn = await self._turns.get(turn_id)
            if turn is None or is_turn_status_terminal(turn.status):
                logger.info(
                    "owner_escalate_terminal_noop",
                    extra={
                        "turn_id": str(turn_id),
                        "status": None if turn is None else turn.status,
                    },
                )
                return False

            approval = await self._approvals.get_by_turn(turn_id)
            if approval is not None and approval.status in {"waiting", "claimed"}:
                await self._approvals.mark_status(turn_id, "cancelled")

            await self._coordinator.transition(turn_id, TurnStatus.ESCALATED)

        await self._notifier.notify_info(
            f"Turn {turn_id} escalated/discarded by owner",
            chat_id=chat_id,
        )
        logger.info(
            "owner_escalate",
            extra={"turn_id": str(turn_id), "chat_id": chat_id},
        )
        return True

    async def _resolve_and_deliver(
        self,
        turn_id: UUID,
        *,
        corrected_text: str | None,
    ) -> DeliveryResult | None:
        turn = await self._turns.get(turn_id)
        if turn is None:
            logger.info("admin_resolve_missing_turn", extra={"turn_id": str(turn_id)})
            return None
        chat_id = turn.chat_id

        claimed: ApprovalRecord | None = None
        text: str = ""
        decision_dump: dict[str, Any] | None = None
        trigger_message_id: int | None = None

        # Claim under chat lock so only one owner resolve wins (BUG-003).
        async with self._coordinator.chat_scope(chat_id):
            turn = await self._turns.get(turn_id)
            if turn is None or is_turn_status_terminal(turn.status):
                logger.info(
                    "admin_resolve_terminal_noop",
                    extra={
                        "turn_id": str(turn_id),
                        "status": None if turn is None else turn.status,
                    },
                )
                return None

            claimed = await self._approvals.claim_waiting(turn_id)
            if claimed is None:
                logger.info(
                    "admin_resolve_claim_lost",
                    extra={"turn_id": str(turn_id)},
                )
                return None

            text = (
                corrected_text
                if corrected_text is not None
                else claimed.draft_text
            )
            decision_dump = claimed.evaluation
            trigger_message_id = (
                claimed.trigger_message_id or turn.trigger_message_id
            )

        # SEC-F1: freeze gate before VIP write (mirror orch autonomous re-check).
        # Fail closed: no deliver when frozen; mark turn failed + cancel claim.
        is_frozen = await self._is_vip_frozen(claimed.vip_id)
        if is_frozen:
            async with self._coordinator.chat_scope(chat_id):
                turn_after = await self._turns.get(turn_id)
                if turn_after is not None and not is_turn_status_terminal(
                    turn_after.status
                ):
                    await self._approvals.mark_status(turn_id, "cancelled")
                    await self._coordinator.mark_failed(
                        turn_id, error="vip_frozen"
                    )
                    try:
                        await self._notifier.notify_info(
                            f"Turn {turn_id} failed: vip_frozen",
                            chat_id=chat_id,
                        )
                    except Exception:
                        logger.exception(
                            "owner_notify_failed_after_vip_frozen",
                            extra={"turn_id": str(turn_id)},
                        )
            logger.info(
                "admin_deliver_vip_frozen",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_id": str(claimed.vip_id) if claimed.vip_id else None,
                },
            )
            return DeliveryResult(
                success=False,
                cancelled=True,
                error="vip_frozen",
            )

        advanced = self._feature_advanced_behavior
        mode = self._effective_delivery_mode(claimed.chat_id)
        if mode == "fake_delivery":
            logger.info(
                "delivery_mode_fake",
                extra={"turn_id": str(turn_id), "chat_id": claimed.chat_id},
            )
        # SEC-F2: is_frozen reflects gate result (False here; True never reaches deliver).
        ctx = DeliveryContext(
            chat_id=claimed.chat_id,
            business_connection_id=claimed.business_connection_id,
            vip_id=claimed.vip_id,
            telegram_message_id=trigger_message_id,
            mode=mode,
            is_frozen=False,
            skip_initial_delay=True,
            allow_split=advanced,
            allow_human_quirks=advanced,
            split_chars=4096,
        )
        # Deliver outside the chat lock so cancel_pending can interrupt mid-flight.
        result = await self._behavior.deliver(
            [text],
            ctx,
            turn_id,
            decision=decision_dump,
        )

        async with self._coordinator.chat_scope(chat_id):
            turn_after = await self._turns.get(turn_id)
            if turn_after is None or is_turn_status_terminal(turn_after.status):
                # Superseded or otherwise terminal mid-flight — do not revive.
                await self._approvals.mark_status(turn_id, "cancelled")
                logger.info(
                    "admin_resolve_aborted_terminal_after_deliver",
                    extra={
                        "turn_id": str(turn_id),
                        "status": None if turn_after is None else turn_after.status,
                        "deliver_success": result.success,
                    },
                )
                return None if not result.cancelled else result

            if result.success:
                approval_status = (
                    "corrected" if corrected_text is not None else "approved"
                )
                await self._approvals.mark_status(turn_id, approval_status)
                await self._coordinator.transition(turn_id, TurnStatus.DELIVERED)
                await self._traces.set_delivery_result(
                    turn_id, result.to_trace_dict()
                )
                # H7.2: append delivered outbound text for HistoryRetriever (owner→dueña).
                # Skip durable history when sandbox is active (should_persist false).
                # Multi-segment: one owner row per message_id when texts align.
                if self._history is not None:
                    if (
                        self._sandbox is not None
                        and not self._sandbox.should_persist(chat_id)  # type: ignore[union-attr]
                    ):
                        logger.info(
                            "owner_history_skipped_sandbox",
                            extra={
                                "turn_id": str(turn_id),
                                "chat_id": chat_id,
                            },
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
                    "admin_delivered",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": claimed.chat_id,
                        "mode": approval_status,
                    },
                )
            elif result.cancelled:
                # Live turn + cancel (rare) — reopen waiting for owner retry.
                await self._approvals.mark_status(turn_id, "waiting")
                logger.info(
                    "admin_deliver_cancelled_reopened",
                    extra={
                        "turn_id": str(turn_id),
                        "error": result.error,
                    },
                )
            else:
                # I.5 permanent deliver failure after retries — do not silent-wait.
                await self._approvals.mark_status(turn_id, "cancelled")
                await self._coordinator.mark_failed(
                    turn_id, error=result.error or "delivery_failed"
                )
                await self._notifier.notify_info(
                    f"Turn {turn_id} failed: delivery_failed ({result.error})",
                    chat_id=claimed.chat_id,
                )
                await self._traces.set_delivery_result(
                    turn_id, result.to_trace_dict()
                )
                logger.info(
                    "admin_deliver_failed",
                    extra={
                        "turn_id": str(turn_id),
                        "error": result.error,
                    },
                )
        return result

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
