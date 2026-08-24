"""Deterministic pre-Director escalation (no Director / no LLM).

Covers forbidden keywords (TAC-06) and J.4 categories (pago / IA / compromiso).
IA path may deliver a fixed VIP template before escalating.
"""

from __future__ import annotations

import logging
from uuid import UUID

from diana.application.j4_triggers import IA_TEMPLATE
from diana.application.ports import (
    BehaviorDeliverer,
    DeliveryContext,
    EscalationNotification,
    EscalationStore,
    OwnerNotifierPort,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.models import TurnStatus

logger = logging.getLogger("diana.application")

FORBIDDEN_TIPO = "palabra_prohibida"
TIPO_PAGO_PRECIO = "pago_precio"
TIPO_IDENTIDAD_IA = "identidad_ia"
TIPO_COMPROMISO_REAL = "compromiso_real"


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
    tipo: str = FORBIDDEN_TIPO,
    reason: str | None = None,
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

    motivo = ",".join(keywords_hit) if keywords_hit else tipo
    await escalations.create(
        turn_id,
        tipo=tipo,
        motivo=motivo,
        business_connection_id=business_connection_id,
    )
    notify_reason = reason or f"{tipo}: {motivo}"
    await notifier.notify_escalation(
        EscalationNotification(
            turn_id=turn_id,
            chat_id=chat_id,
            reason=notify_reason,
            vip_text=text,
            tipo=tipo,
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
            "tipo": tipo,
        },
    )
    return turn_id


async def handle_deterministic_template_escalate(
    *,
    coordinator: TurnCoordinator,
    escalations: EscalationStore,
    notifier: OwnerNotifierPort,
    behavior: BehaviorDeliverer,
    chat_id: int,
    text: str,
    vip_id: UUID | None,
    business_connection_id: str | None,
    message_id: int | None,
    keywords_hit: list[str],
    template: str = IA_TEMPLATE,
    tipo: str = TIPO_IDENTIDAD_IA,
    is_frozen: bool = False,
    reason: str | None = None,
) -> UUID:
    """Deliver fixed VIP product template (if business connection present), then escalate.

    Still no Director/LLM. Soft deliver failure (success=False) and exceptions
    are logged; escalate still proceeds so the owner always sees the event.

    ``template`` is intentionally the product IA constant (``IA_TEMPLATE``).
    Empty/whitespace overrides fall back to ``IA_TEMPLATE`` — free-form product
    copy is not a supported public API surface for J.4 identity.

    ``is_frozen`` is honored on DeliveryContext. Production stack drops frozen
    VIPs in FreezeCheckMiddleware before this path; pass-through remains safe.
    """
    record = await coordinator.begin_turn(
        chat_id=chat_id,
        trigger_message_id=message_id,
        vip_id=vip_id,
    )
    turn_id = record.id
    deliver_text = template.strip() if template and template.strip() else IA_TEMPLATE

    if business_connection_id:
        ctx = DeliveryContext(
            chat_id=chat_id,
            business_connection_id=str(business_connection_id),
            vip_id=vip_id,
            telegram_message_id=message_id,
            is_frozen=is_frozen,
        )
        try:
            result = await behavior.deliver([deliver_text], ctx, turn_id)
            success = getattr(result, "success", None)
            if success is False:
                logger.warning(
                    "deterministic_template_deliver_soft_fail",
                    extra={
                        "turn_id": str(turn_id),
                        "chat_id": chat_id,
                        "tipo": tipo,
                        "error": getattr(result, "error", None),
                        "cancelled": getattr(result, "cancelled", False),
                    },
                )
        except Exception:
            logger.exception(
                "deterministic_template_deliver_failed",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "tipo": tipo,
                },
            )
    else:
        logger.warning(
            "deterministic_template_skip_deliver_no_bc",
            extra={"turn_id": str(turn_id), "chat_id": chat_id, "tipo": tipo},
        )

    await coordinator.transition(turn_id, TurnStatus.ESCALATED)

    motivo = ",".join(keywords_hit) if keywords_hit else tipo
    await escalations.create(
        turn_id,
        tipo=tipo,
        motivo=motivo,
        business_connection_id=business_connection_id,
    )
    notify_reason = reason or f"{tipo}: {motivo}"
    await notifier.notify_escalation(
        EscalationNotification(
            turn_id=turn_id,
            chat_id=chat_id,
            reason=notify_reason,
            vip_text=text,
            tipo=tipo,
            business_connection_id=business_connection_id,
        )
    )
    await escalations.mark_notified(turn_id)
    logger.info(
        "deterministic_template_escalation",
        extra={
            "turn_id": str(turn_id),
            "chat_id": chat_id,
            "keywords": keywords_hit,
            "tipo": tipo,
        },
    )
    return turn_id


__all__ = [
    "FORBIDDEN_TIPO",
    "TIPO_COMPROMISO_REAL",
    "TIPO_IDENTIDAD_IA",
    "TIPO_PAGO_PRECIO",
    "handle_deterministic_escalation",
    "handle_deterministic_template_escalate",
]
