"""ErrorHandlerMiddleware — outermost I/O boundary; swallow handler faults."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger("diana.telegram")


class ErrorHandlerMiddleware(BaseMiddleware):
    """Catch unhandled handler/middleware exceptions at the Telegram edge.

    Logs with stack, answers CallbackQuery with show_alert when possible,
    and swallows (never re-raises) so the update path stays alive.
    No constructor deps — pure I/O boundary.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            chat_id = None
            if hasattr(event, "chat") and event.chat is not None:
                chat_id = getattr(event.chat, "id", None)
            elif hasattr(event, "message") and event.message is not None:
                chat = getattr(event.message, "chat", None)
                chat_id = getattr(chat, "id", None) if chat else None
            logger.exception(
                "telegram_handler_error",
                extra={
                    "event_type": type(event).__name__,
                    "chat_id": chat_id,
                },
            )
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(
                        "Something went wrong. Try again.",
                        show_alert=True,
                    )
                except Exception:
                    logger.exception("telegram_error_handler_answer_failed")
            return None


__all__ = ["ErrorHandlerMiddleware"]
