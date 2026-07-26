"""ErrorHandlerMiddleware — outermost I/O boundary; swallow handler faults."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger("diana.telegram")


def _event_log_extra(event: TelegramObject) -> dict[str, Any]:
    """Short correlation fields for swallowed faults (no message text / PII body)."""
    extra: dict[str, Any] = {"event_type": type(event).__name__}
    from_user = getattr(event, "from_user", None)
    if from_user is not None:
        extra["telegram_user_id"] = getattr(from_user, "id", None)

    if isinstance(event, CallbackQuery):
        extra["callback_query_id"] = getattr(event, "id", None)
        extra["callback_data"] = getattr(event, "data", None)
        msg = getattr(event, "message", None)
        if msg is not None:
            chat = getattr(msg, "chat", None)
            extra["chat_id"] = getattr(chat, "id", None) if chat else None
            extra["message_id"] = getattr(msg, "message_id", None)
        else:
            extra["chat_id"] = None
            extra["message_id"] = None
        return extra

    if isinstance(event, Message):
        chat = getattr(event, "chat", None)
        extra["chat_id"] = getattr(chat, "id", None) if chat else None
        extra["message_id"] = getattr(event, "message_id", None)
        return extra

    # Best-effort for other TelegramObject shapes.
    chat = getattr(event, "chat", None)
    if chat is not None:
        extra["chat_id"] = getattr(chat, "id", None)
    msg = getattr(event, "message", None)
    if msg is not None:
        chat = getattr(msg, "chat", None)
        extra.setdefault("chat_id", getattr(chat, "id", None) if chat else None)
        extra["message_id"] = getattr(msg, "message_id", None)
    return extra


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
            logger.exception(
                "telegram_handler_error",
                extra=_event_log_extra(event),
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
