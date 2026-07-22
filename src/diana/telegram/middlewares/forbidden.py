"""ForbiddenKeywordsMiddleware — deterministic escalate, zero Director."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.deterministic_escalate import handle_deterministic_escalation
from diana.application.ports import EscalationStore, OwnerNotifierPort
from diana.application.turn_coordinator import TurnCoordinator

logger = logging.getLogger("diana.telegram")


def match_forbidden_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return list of keywords found in text (case-insensitive word/phrase)."""
    if not text or not keywords:
        return []
    lower = text.lower()
    hits: list[str] = []
    for kw in keywords:
        k = (kw or "").strip().lower()
        if not k:
            continue
        # Phrase or whole-word style match.
        if " " in k:
            if k in lower:
                hits.append(kw.strip())
        else:
            if re.search(rf"\b{re.escape(k)}\b", lower, flags=re.IGNORECASE):
                hits.append(kw.strip())
    return hits


class ForbiddenKeywordsMiddleware(BaseMiddleware):
    """On keyword hit: handle_deterministic_escalation and stop pipeline."""

    def __init__(
        self,
        *,
        keywords: list[str],
        coordinator: TurnCoordinator,
        escalations: EscalationStore,
        notifier: OwnerNotifierPort,
    ) -> None:
        self._keywords = list(keywords)
        self._coordinator = coordinator
        self._escalations = escalations
        self._notifier = notifier

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        text = event.text or event.caption or ""
        hits = match_forbidden_keywords(text, self._keywords)
        if not hits:
            return await handler(event, data)

        chat_id = event.chat.id if event.chat else 0
        bc = data.get("business_connection_id") or event.business_connection_id
        vip_id = data.get("vip_id")
        if vip_id is not None and not isinstance(vip_id, UUID):
            try:
                vip_id = UUID(str(vip_id))
            except ValueError:
                vip_id = None

        await handle_deterministic_escalation(
            coordinator=self._coordinator,
            escalations=self._escalations,
            notifier=self._notifier,
            chat_id=chat_id,
            text=text,
            vip_id=vip_id,
            business_connection_id=bc,
            message_id=event.message_id,
            keywords_hit=hits,
        )
        logger.info(
            "forbidden_short_circuit",
            extra={"chat_id": chat_id, "keywords": hits},
        )
        # Stop VIP pipeline — do not call orchestrator / Director.
        return None


__all__ = ["ForbiddenKeywordsMiddleware", "match_forbidden_keywords"]
