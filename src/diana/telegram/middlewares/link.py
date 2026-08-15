"""LinkCoordinatorMiddleware — consume Lucien→Diana [LINK] messages early."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.link import LinkCoordinator

logger = logging.getLogger("diana.telegram")


class LinkCoordinatorMiddleware(BaseMiddleware):
    """Message-only gate: [LINK] traffic is consumed, everything else passes."""

    def __init__(
        self,
        *,
        link: LinkCoordinator | None = None,
        link_chat_id: int | None = None,
        enabled: bool = False,
    ) -> None:
        self._link = link
        self._link_chat_id = link_chat_id
        self._enabled = enabled

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Pass-through: flag off, no link, no chat, not a Message, or not a
        # business message. Message-only no-op on message/callback observers.
        if not self._enabled or self._link is None or self._link_chat_id is None:
            return await handler(event, data)
        if not isinstance(event, Message):
            return await handler(event, data)
        bc = data.get("business_connection_id") or getattr(
            event, "business_connection_id", None
        )
        if not bc:
            return await handler(event, data)
        chat = getattr(event, "chat", None)
        chat_id = getattr(chat, "id", None) if chat else None
        text = getattr(event, "text", None) or ""
        if chat_id != self._link_chat_id or not text.startswith("[LINK]"):
            return await handler(event, data)
        # Coordination traffic: consume unconditionally (return None), so it
        # never reaches TurnOrchestrator / message_history / history.append.
        try:
            payload = json.loads(text[len("[LINK]") :])
            if payload.get("event") != "vip_kicked":
                raise ValueError("unexpected event")
            await self._link.handle_kick_event(
                event_id=str(payload["event_id"]),
                user_id=int(payload["user_id"]),
                username=payload.get("username"),
                reason=str(payload["reason"]),
                channel_id=payload.get("channel_id"),
                channel_name=payload.get("channel_name"),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.info(
                "link_malformed",
                extra={"chat_id": chat_id, "error": str(exc)},
            )
        return None


__all__ = ["LinkCoordinatorMiddleware"]
