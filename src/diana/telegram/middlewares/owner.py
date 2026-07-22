"""OwnerDetectionMiddleware — owner traffic short-circuits VIP pipeline."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from diana.application.ports import BehaviorCanceller

logger = logging.getLogger("diana.telegram")


class OwnerDetectionMiddleware(BaseMiddleware):
    """If sender is owner: cancel_pending for chat, stop VIP pipeline.

    Owner private messages (commands / correct text) are allowed through when
    the event is *not* a Business message (no business_connection_id).
    """

    def __init__(
        self,
        *,
        owner_telegram_id: int,
        behavior: BehaviorCanceller,
    ) -> None:
        self._owner_id = owner_telegram_id
        self._behavior = behavior

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None) if user is not None else None

        if user_id is None or user_id != self._owner_id:
            return await handler(event, data)

        data["is_owner"] = True

        # Business messages from owner (edge) — observe + cancel, no VIP pipeline.
        bc = data.get("business_connection_id") or getattr(
            event, "business_connection_id", None
        )
        if bc:
            chat = getattr(event, "chat", None)
            chat_id = getattr(chat, "id", None) if chat else None
            if chat_id is not None:
                await self._behavior.cancel_pending(chat_id, "owner_message")
            logger.info(
                "owner_business_observed",
                extra={"chat_id": chat_id},
            )
            return None

        # Private owner messages continue to admin/callback routers.
        return await handler(event, data)


__all__ = ["OwnerDetectionMiddleware"]
