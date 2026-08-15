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
        # Pass-through: flag off, no link, no chat, or not a Message.
        # Message-only no-op on message/callback observers.
        if not self._enabled or self._link is None or self._link_chat_id is None:
            return await handler(event, data)
        if not isinstance(event, Message):
            return await handler(event, data)
        chat = getattr(event, "chat", None)
        chat_id = getattr(chat, "id", None) if chat else None
        text = getattr(event, "text", None) or ""
        if chat_id != self._link_chat_id or not text.startswith("[LINK]"):
            return await handler(event, data)
        # Coordination traffic: parse and validate only. Consume unconditionally
        # (return None) so it never reaches TurnOrchestrator / message_history /
        # history.append. The coordinator call runs OUTSIDE the try so real
        # application errors propagate to ErrorHandlerMiddleware instead of being
        # mislabeled link_malformed.
        try:
            payload = json.loads(text[len("[LINK]") :])
            if not isinstance(payload, dict):
                raise ValueError("payload is not an object")
            if payload.get("event") != "vip_kicked":
                raise ValueError("unexpected event")
            event_id = payload["event_id"]
            reason = payload["reason"]
            if not isinstance(event_id, str) or not event_id:
                raise ValueError("invalid event_id")
            if not isinstance(reason, str) or not reason:
                raise ValueError("invalid reason")
            user_id = int(payload["user_id"])
            username = payload.get("username")
            if username is not None and not isinstance(username, str):
                username = str(username)
            channel_id = payload.get("channel_id")
            if channel_id is not None:
                channel_id = int(channel_id)
            channel_name = payload.get("channel_name")
            if channel_name is not None and not isinstance(channel_name, str):
                channel_name = str(channel_name)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, OverflowError) as exc:
            logger.info(
                "link_malformed",
                extra={"chat_id": chat_id, "error": str(exc)},
            )
            return None
        await self._link.handle_kick_event(
            event_id=event_id,
            user_id=user_id,
            username=username,
            reason=reason,
            channel_id=channel_id,
            channel_name=channel_name,
        )
        return None


__all__ = ["LinkCoordinatorMiddleware"]
