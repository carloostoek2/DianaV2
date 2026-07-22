"""AuthMiddleware — VIP allowlist gate."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.ports import VipStore

logger = logging.getLogger("diana.telegram")


class AuthMiddleware(BaseMiddleware):
    """Drop non-allowlist VIP business traffic; inject vip_id when allowed."""

    def __init__(self, *, vips: VipStore) -> None:
        self._vips = vips

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Owner private path already marked — skip allowlist for non-business.
        if data.get("is_owner") and not data.get("business_connection_id"):
            return await handler(event, data)

        if not isinstance(event, Message):
            return await handler(event, data)

        # Only gate business messages (VIP path).
        bc = data.get("business_connection_id") or event.business_connection_id
        if not bc:
            # Non-business messages (admin private) pass through without vip_id.
            return await handler(event, data)

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
