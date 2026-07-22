"""Deterministic forbidden-keyword escalation (no Director / no LLM)."""

from __future__ import annotations

import logging
from uuid import UUID

from diana.application.ports import (
    EscalationNotification,
    EscalationStore,
    OwnerNotifierPort,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.models import TurnStatus

logger = logging.getLogger("diana.application")

FORBIDDEN_TIPO = "palabra_prohibida"


async def handle_deterministic_escalation(
    *,
    coordinator: TurnCoordinator,
    escalations: EscalationStore,
    notifier: OwnerNotifierPort,
    chat_id: int,
    text: str,
    vip_id: UUID | None,
    business_connection_id: str | None,
    message_id: int | None,
    keywords_hit: list[str],
) -> UUID:
    """Create an escalated turn without CognitiveDirector or LLM.

    Steps:
    1. begin_turn (mint turn_id; supersede cascade OK)
    2. transition → escalated
    3. EscalationStore.create
    4. notifier.notify_escalation
    5. mark_notified
    6. return turn_id
    """
    record = await coordinator.begin_turn(
        chat_id=chat_id,
        trigger_message_id=message_id,
        vip_id=vip_id,
    )
    turn_id = record.id
    await coordinator.transition(turn_id, TurnStatus.ESCALATED)

    motivo = ",".join(keywords_hit) if keywords_hit else "forbidden"
    await escalations.create(turn_id, tipo=FORBIDDEN_TIPO, motivo=motivo)
    await notifier.notify_escalation(
        EscalationNotification(
            turn_id=turn_id,
            chat_id=chat_id,
            reason=f"forbidden keywords: {motivo}",
            vip_text=text,
            tipo=FORBIDDEN_TIPO,
            business_connection_id=business_connection_id,
        )
    )
    await escalations.mark_notified(turn_id)
    logger.info(
        "deterministic_escalation",
        extra={
            "turn_id": str(turn_id),
            "chat_id": chat_id,
            "keywords": keywords_hit,
        },
    )
    return turn_id


__all__ = ["FORBIDDEN_TIPO", "handle_deterministic_escalation"]
