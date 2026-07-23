"""OwnerDetectionMiddleware — owner traffic short-circuits VIP pipeline."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from diana.application.turn_coordinator import TurnCoordinator

logger = logging.getLogger("diana.telegram")


class OwnerDetectionMiddleware(BaseMiddleware):
    """If sender is owner on a business chat: coordinate discard, stop pipeline.

    Owner private messages (commands / correct text) are allowed through when
    the event is *not* a Business message (no business_connection_id). Private
    admin traffic must not call owner discard for a VIP chat.
    """

    def __init__(
        self,
        *,
        owner_telegram_id: int,
        coordinator: TurnCoordinator,
    ) -> None:
        self._owner_id = owner_telegram_id
        self._coordinator = coordinator

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

        # Business messages from owner — supersede live turn + cascade cancel.
        bc = data.get("business_connection_id") or getattr(
            event, "business_connection_id", None
        )
        if bc:
            chat = getattr(event, "chat", None)
            chat_id = getattr(chat, "id", None) if chat else None
            action: str | None = None
            if chat_id is not None:
                result = await self._coordinator.coordinate(
                    chat_id,
                    "owner",
                    trigger_message_id=getattr(event, "message_id", None),
                )
                action = result.action
            logger.info(
                "owner_business_observed",
                extra={"chat_id": chat_id, "action": action},
            )
            return None

        # Private owner messages continue to admin/callback routers.
        return await handler(event, data)


__all__ = ["OwnerDetectionMiddleware"]
