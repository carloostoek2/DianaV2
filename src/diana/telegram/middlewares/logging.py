"""LoggingMiddleware — request logging only."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

logger = logging.getLogger("diana.telegram")


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat_id = None
        if hasattr(event, "chat") and event.chat is not None:
            chat_id = getattr(event.chat, "id", None)
        elif hasattr(event, "message") and event.message is not None:
            chat = getattr(event.message, "chat", None)
            chat_id = getattr(chat, "id", None) if chat else None
        logger.info(
            "telegram_update",
            extra={"chat_id": chat_id, "event_type": type(event).__name__},
        )
        return await handler(event, data)


__all__ = ["LoggingMiddleware"]
