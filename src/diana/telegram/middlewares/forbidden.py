"""ForbiddenKeywordsMiddleware — business VIP short-circuit, zero Director."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.deterministic_escalate import handle_deterministic_escalation
from diana.application.ports import EscalationStore, OwnerNotifierPort, VipStore
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
    """On business VIP keyword hit: deterministic escalate and stop pipeline.

    Does **not** run on private (non-business) traffic — owner free-text correct
    and non-owner DMs must not short-circuit or supersede VIP chats.
    """

    def __init__(
        self,
        *,
        keywords: list[str],
        coordinator: TurnCoordinator,
        escalations: EscalationStore,
        notifier: OwnerNotifierPort,
        vips: VipStore | None = None,
    ) -> None:
        self._keywords = list(keywords)
        self._coordinator = coordinator
        self._escalations = escalations
        self._notifier = notifier
        self._vips = vips

    def set_keywords(self, keywords: list[str]) -> None:
        """Replace keyword list in place (boot load from system_config)."""
        self._keywords = list(keywords)

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

        text = event.text or event.caption or ""
        hits = match_forbidden_keywords(text, self._keywords)
        if not hits:
            return await handler(event, data)

        chat_id = event.chat.id if event.chat else 0
        vip_id = data.get("vip_id")
        if vip_id is not None and not isinstance(vip_id, UUID):
            try:
                vip_id = UUID(str(vip_id))
            except ValueError:
                vip_id = None

        # Auth runs after Forbidden — resolve VIP by telegram user when missing.
        if vip_id is None and self._vips is not None:
            user = event.from_user
            if user is not None:
                rec = await self._vips.get_by_telegram_user_id(user.id)
                if rec is not None:
                    vip_id = rec.id

        await handle_deterministic_escalation(
            coordinator=self._coordinator,
            escalations=self._escalations,
            notifier=self._notifier,
            chat_id=chat_id,
            text=text,
            vip_id=vip_id,
            business_connection_id=str(bc),
            message_id=event.message_id,
            keywords_hit=hits,
        )
        logger.info(
            "forbidden_short_circuit",
            extra={
                "chat_id": chat_id,
                "keywords": hits,
                "vip_id": str(vip_id) if vip_id else None,
            },
        )
        # Stop VIP pipeline — do not call orchestrator / Director.
        return None


__all__ = ["ForbiddenKeywordsMiddleware", "match_forbidden_keywords"]
