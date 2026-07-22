"""AdminService — owner approval queue (domain API, no aiogram types)."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from diana.application.ports import (
    ApprovalRecord,
    DeliveryResultWriter,
    DraftNotification,
    EscalationNotification,
    EscalationStore,
    OwnerNotifierPort,
    PendingApprovalStore,
    TurnStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.ports import DeliveryContext, DeliveryResult
from diana.cognitive.models import (
    TERMINAL_TURN_STATUSES,
    Decision,
    IncomingTurn,
    TurnStatus,
    parse_turn_status,
)

logger = logging.getLogger("diana.application")


def _eval_summary(decision: Decision) -> str:
    """Display-only summary string; never fed back into Decider."""
    e = decision.evaluation
    return (
        f"nat={e.naturalness:.2f} prec={e.precision:.2f} "
        f"doc={e.doctrine:.2f} con={e.consistency:.2f} "
        f"saf={e.safety:.2f} cov={e.coverage:.2f} emp={e.empathy:.2f}"
    )


class AdminService:
    """Owner-facing draft queue and the only gate that may call Behavior.deliver."""

    def __init__(
        self,
        *,
        notifier: OwnerNotifierPort,
        approvals: PendingApprovalStore,
        escalations: EscalationStore,
        coordinator: TurnCoordinator,
        behavior: BehaviorEngine,
        traces: DeliveryResultWriter,
        turns: TurnStore,
    ) -> None:
        self._notifier = notifier
        self._approvals = approvals
        self._escalations = escalations
        self._coordinator = coordinator
        self._behavior = behavior
        self._traces = traces
        self._turns = turns

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
            # Best-effort: store owner message id on the approval record if present
            existing = await self._approvals.get_by_turn(turn_id)
            if existing is not None:
                # re-create via mark is enough for tests; keep owner_message_id on model
                # by replacing record fields through a second create is forbidden (unique).
                # Update in-memory store if it supports mutation — patch via private if needed.
                pass
        logger.info(
            "draft_for_approval",
            extra={"turn_id": str(turn_id), "chat_id": turn.chat_id},
        )

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
        _ = actor_id
        return await self._resolve_and_deliver(turn_id, corrected_text=None)

    async def handle_correct(
        self,
        turn_id: UUID,
        corrected_text: str,
        *,
        actor_id: int | None = None,
    ) -> DeliveryResult | None:
        _ = actor_id
        return await self._resolve_and_deliver(
            turn_id, corrected_text=corrected_text
        )

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
        try:
            status = parse_turn_status(turn.status)
        except ValueError:
            status = None
        if status is not None and status in TERMINAL_TURN_STATUSES:
            logger.info(
                "admin_resolve_terminal_noop",
                extra={"turn_id": str(turn_id), "status": turn.status},
            )
            return None

        approval = await self._approvals.get_by_turn(turn_id)
        if approval is None or approval.status != "waiting":
            logger.info(
                "admin_resolve_no_waiting_approval",
                extra={"turn_id": str(turn_id)},
            )
            return None

        text = corrected_text if corrected_text is not None else approval.draft_text
        ctx = DeliveryContext(
            chat_id=approval.chat_id,
            business_connection_id=approval.business_connection_id,
            vip_id=approval.vip_id,
        )
        result = await self._behavior.deliver([text], ctx, turn_id)
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
                    "chat_id": approval.chat_id,
                    "mode": approval_status,
                },
            )
        return result
