"""ForbiddenKeywordsMiddleware — business VIP short-circuit, zero Director.

Order of classification (first win): J.4 pago_precio → compromiso_real →
system_config forbidden list (palabra_prohibida).

H6: pure IA identity probes are not short-circuited here; they reach
CognitiveDirector TemplateGate for supervised approve.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.deterministic_escalate import (
    handle_deterministic_escalation,
)
from diana.application.j4_triggers import (
    classify_j4_text,
    match_keywords,
)

from diana.application.ports import (
    BehaviorDeliverer,
    EscalationStore,
    OwnerNotifierPort,
    VipStore,
)
from diana.application.turn_coordinator import TurnCoordinator

logger = logging.getLogger("diana.telegram")

# H6 annex deteccion_ia triggers — owned by CognitiveDirector TemplateGate.
# Must never silent-escalate as palabra_prohibida (legacy seed had "eres un bot").
TEMPLATE_GATE_OWNED_FORBIDDEN_PHRASES: frozenset[str] = frozenset(
    {
        "eres una ia",
        "eres un bot",
        "eres ia",
        "hablo con una ia",
        "hablo con un bot",
        "eres real",
    }
)


def sanitize_forbidden_keywords(keywords: list[str]) -> list[str]:
    """Drop TemplateGate-owned annex phrases; keep real forbidden words."""
    cleaned: list[str] = []
    for kw in keywords:
        key = str(kw).strip().lower()
        if not key or key in TEMPLATE_GATE_OWNED_FORBIDDEN_PHRASES:
            continue
        cleaned.append(str(kw))
    return cleaned


def match_forbidden_keywords(text: str, keywords: list[str]) -> list[str]:
    """Thin wrapper over application ``match_keywords`` (single algorithm)."""
    return match_keywords(text, keywords)


# F4: commercial vocabulary that must FLOW through the atencion pipeline
# (payment/sales scripts: "pago", "transferencia" are the buying vocabulary).
# Excluded from the forbidden check for the atencion channel ONLY — VIP
# keeps the full list untouched (J.4 + forbidden keywords). "reclamación"
# still escalates on both channels (a complaint is owner territory).
ATENCION_COMMERCIAL_EXEMPT_KEYWORDS = frozenset({"pago", "transferencia"})


class ForbiddenKeywordsMiddleware(BaseMiddleware):
    """On business VIP J.4/forbidden hit: deterministic escalate and stop pipeline.

    Does **not** run on private (non-business) traffic — owner free-text correct
    and non-owner DMs must not short-circuit or supersede VIP chats.

    When ``vips`` is injected, only allowlisted VIP users escalate (defense in
    depth if stack order is Auth → Forbidden). Non-VIP business continues to
    the next middleware/handler (promo/drop).
    """

    def __init__(
        self,
        *,
        keywords: list[str],
        coordinator: TurnCoordinator,
        escalations: EscalationStore,
        notifier: OwnerNotifierPort,
        vips: VipStore | None = None,
        behavior: BehaviorDeliverer | None = None,
        feature_general_mode_enabled: bool = False,
    ) -> None:
        self._keywords = sanitize_forbidden_keywords(list(keywords))
        self._coordinator = coordinator
        self._escalations = escalations
        self._notifier = notifier
        self._vips = vips
        self._behavior = behavior
        self._feature_general = bool(feature_general_mode_enabled)

    def set_keywords(self, keywords: list[str]) -> None:
        """Replace keyword list in place (boot load from system_config)."""
        self._keywords = sanitize_forbidden_keywords(list(keywords))


    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        # F1: forbidden short-circuit is Business VIP traffic only.
        bc = data.get("business_connection_id") or getattr(
            event, "business_connection_id", None
        )
        if not bc:
            return await handler(event, data)

        # Owner business path is already stopped by OwnerDetection; belt-and-suspenders.
        if data.get("is_owner"):
            return await handler(event, data)

        # VIP allowlist gate when store present (non-VIP → pass; no owner spam).
        chat_id = event.chat.id if event.chat else 0
        user = event.from_user
        is_atencion_general = False
        if self._vips is not None:
            if user is None:
                return await handler(event, data)
            allowed = await self._vips.is_allowed(user.id)
            if not allowed:
                # REQ-ATN-08: atencion channel (general mode) must still be
                # checked for forbidden keywords — the anti-explicit guarantee
                # covers both channels. Flag-gated so flag-OFF behavior is
                # byte-identical to today (non-VIP skips as before).
                if self._feature_general and data.get("channel_type") == "atencion":
                    logger.info(
                        "forbidden_atencion_enforced",
                        extra={
                            "chat_id": chat_id,
                            "telegram_user_id": user.id,
                        },
                    )
                    is_atencion_general = True
                else:
                    logger.info(
                        "j4_forbidden_skip_non_vip",
                        extra={
                            "chat_id": chat_id,
                            "telegram_user_id": user.id,
                        },
                    )
                    return await handler(event, data)

        text = event.text or event.caption or ""
        if is_atencion_general:
            # REQ-ATN-08: atencion non-VIP is scoped to forbidden-keyword
            # matching only (no J.4 classification); escalation mechanism is
            # identical to VIP. VIP path below keeps full J.4 untouched.
            # F4: commercial words (pago/transferencia) are exempt for the
            # atencion channel so the sales flow (payment scripts → owner DM
            # on intent) is not short-circuited by the deterministic gate.
            atencion_keywords = [
                k
                for k in self._keywords
                if k not in ATENCION_COMMERCIAL_EXEMPT_KEYWORDS
            ]
            forbidden_hits = match_forbidden_keywords(text, atencion_keywords)
            if not forbidden_hits:
                return await handler(event, data)
            j4 = None
        else:
            j4 = classify_j4_text(text)
            forbidden_hits = (
                match_forbidden_keywords(text, self._keywords) if not j4 else []
            )
            if j4 is None and not forbidden_hits:
                return await handler(event, data)

        vip_id = data.get("vip_id")
        if vip_id is not None and not isinstance(vip_id, UUID):
            try:
                vip_id = UUID(str(vip_id))
            except ValueError:
                vip_id = None

        # Resolve VIP by telegram user when Auth has not set vip_id yet.
        if vip_id is None and self._vips is not None and user is not None:
            rec = await self._vips.get_by_telegram_user_id(user.id)
            if rec is not None:
                vip_id = rec.id

        if j4 is not None:
            await handle_deterministic_escalation(
                coordinator=self._coordinator,
                escalations=self._escalations,
                notifier=self._notifier,
                chat_id=chat_id,
                text=text,
                vip_id=vip_id,
                business_connection_id=str(bc),
                message_id=event.message_id,
                keywords_hit=j4.keywords_hit,
                tipo=j4.tipo,
            )
            logger.info(
                "j4_short_circuit",
                extra={
                    "chat_id": chat_id,
                    "keywords": j4.keywords_hit,
                    "tipo": j4.tipo,
                    "vip_id": str(vip_id) if vip_id else None,
                },
            )
            return None

        await handle_deterministic_escalation(
            coordinator=self._coordinator,
            escalations=self._escalations,
            notifier=self._notifier,
            chat_id=chat_id,
            text=text,
            vip_id=vip_id,
            business_connection_id=str(bc),
            message_id=event.message_id,
            keywords_hit=forbidden_hits,
        )
        logger.info(
            "forbidden_short_circuit",
            extra={
                "chat_id": chat_id,
                "keywords": forbidden_hits,
                "vip_id": str(vip_id) if vip_id else None,
            },
        )
        # Stop VIP pipeline — do not call orchestrator / Director.
        return None


__all__ = [
    "ForbiddenKeywordsMiddleware",
    "TEMPLATE_GATE_OWNED_FORBIDDEN_PHRASES",
    "match_forbidden_keywords",
    "sanitize_forbidden_keywords",
]

