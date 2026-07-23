"""AdminService — owner approval queue (domain API, no aiogram types)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from diana.application.ports import (
    ApprovalRecord,
    BehaviorDeliverer,
    DeliveryResultWriter,
    DraftNotification,
    EscalationNotification,
    EscalationStore,
    OwnerNotifierPort,
    PendingApprovalStore,
    TurnStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.ports import DeliveryContext, DeliveryResult
from diana.cognitive.models import (
    TERMINAL_TURN_STATUSES,
    Decision,
    IncomingTurn,
    TurnStatus,
    parse_turn_status,
)

logger = logging.getLogger("diana.application")


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


def _is_terminal(status: str) -> bool:
    try:
        return parse_turn_status(status) in TERMINAL_TURN_STATUSES
    except ValueError:
        return False


class AdminService:
    """Owner-facing draft queue and the only gate that may call Behavior.deliver."""

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
    ) -> None:
        self._notifier = notifier
        self._approvals = approvals
        self._escalations = escalations
        self._coordinator = coordinator
        self._behavior = behavior
        self._traces = traces
        self._turns = turns
        self._owner_telegram_id = owner_telegram_id

    def _assert_owner(self, actor_id: int | None) -> None:
        if actor_id is None or actor_id != self._owner_telegram_id:
            raise OwnerAuthError(
                f"actor_id {actor_id!r} is not the configured owner"
            )

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
        record = ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=turn.chat_id,
            business_connection_id=bc,
            draft_text=draft,
            status="waiting",
            vip_id=turn.vip_id,
            cognitive_summary=decision.reason,
            evaluation=decision.evaluation.model_dump(mode="json"),
            trigger_message_id=turn.telegram_message_id,
        )
        await self._approvals.create_waiting(record)
        owner_mid = await self._notifier.notify_draft(
            DraftNotification(
                turn_id=turn_id,
                chat_id=turn.chat_id,
                vip_text=turn.text,
                draft_text=draft,
                reason=decision.reason,
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
        tipo = "semantica"
        await self._escalations.create(
            turn_id, tipo=tipo, motivo=decision.reason
        )
        await self._notifier.notify_escalation(
            EscalationNotification(
                turn_id=turn_id,
                chat_id=turn.chat_id,
                reason=decision.reason,
                vip_text=turn.text,
                tipo=tipo,
                business_connection_id=turn.business_connection_id,
            )
        )
        await self._escalations.mark_notified(turn_id)
        logger.info(
            "escalation_notified",
            extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
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
        return await self._resolve_and_deliver(
            turn_id, corrected_text=corrected_text.strip()
        )

    async def is_pending_approval(self, turn_id: UUID) -> bool:
        """True when turn is non-terminal and has a waiting approval."""
        turn = await self._turns.get(turn_id)
        if turn is None or _is_terminal(turn.status):
            return False
        approval = await self._approvals.get_by_turn(turn_id)
        return approval is not None and approval.status == "waiting"

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
            if turn is None or _is_terminal(turn.status):
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
            if turn is None or _is_terminal(turn.status):
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

        ctx = DeliveryContext(
            chat_id=claimed.chat_id,
            business_connection_id=claimed.business_connection_id,
            vip_id=claimed.vip_id,
            telegram_message_id=trigger_message_id,
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
            if turn_after is None or _is_terminal(turn_after.status):
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
                logger.info(
                    "admin_delivered",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": claimed.chat_id,
                        "mode": approval_status,
                    },
                )
            else:
                # Deliver failed/cancelled while turn still live — release claim.
                await self._approvals.mark_status(turn_id, "waiting")
                logger.info(
                    "admin_deliver_failed_reopened",
                    extra={
                        "turn_id": str(turn_id),
                        "error": result.error,
                        "cancelled": result.cancelled,
                    },
                )
        return result
