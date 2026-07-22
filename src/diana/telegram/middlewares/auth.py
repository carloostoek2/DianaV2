"""AuthMiddleware — VIP allowlist gate + drop non-owner private spam."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.ports import VipStore

logger = logging.getLogger("diana.telegram")


class AuthMiddleware(BaseMiddleware):
    """Gate business VIP allowlist; drop non-owner private messages."""

    def __init__(self, *, vips: VipStore) -> None:
        self._vips = vips

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            # Callbacks etc. — owner check happens in handlers via actor_id.
            return await handler(event, data)

        bc = data.get("business_connection_id") or event.business_connection_id

        # Private (non-business) messages: only owner admin path continues.
        if not bc:
            if data.get("is_owner"):
                return await handler(event, data)
            logger.info(
                "auth_drop_private_non_owner",
                extra={
                    "telegram_user_id": getattr(
                        getattr(event, "from_user", None), "id", None
                    )
                },
            )
            return None

        user = event.from_user
        if user is None:
            logger.info("auth_drop_no_user")
            return None

        allowed = await self._vips.is_allowed(user.id)
        if not allowed:
            logger.info(
                "auth_drop_not_allowed",
                extra={"telegram_user_id": user.id},
            )
            return None

        rec = await self._vips.get_by_telegram_user_id(user.id)
        if rec is not None:
            data["vip_id"] = rec.id
            data["vip_record"] = rec
        return await handler(event, data)


__all__ = ["AuthMiddleware"]
