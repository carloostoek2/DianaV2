"""BusinessConnectionMiddleware — inject business_connection_id into data."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class BusinessConnectionMiddleware(BaseMiddleware):
    """Extract Message.business_connection_id into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bc = getattr(event, "business_connection_id", None)
        if bc is None and hasattr(event, "message") and event.message is not None:
            bc = getattr(event.message, "business_connection_id", None)
        if bc is not None:
            data["business_connection_id"] = bc
        return await handler(event, data)


__all__ = ["BusinessConnectionMiddleware"]
