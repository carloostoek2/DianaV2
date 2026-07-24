"""FreezeCheckMiddleware — VIP freeze enforcement for message handlers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.ports import VipStore

logger = logging.getLogger("diana.telegram")


class FreezeCheckMiddleware(BaseMiddleware):
    """Drop messages from VIPs whose frozen_until > now (silent discard).

    Must run AFTER AuthMiddleware so that ``data["vip_record"]`` is available
    for Message events. For non-Message events (callbacks, etc.) this is a
    no-op pass-through.
    """

    def __init__(self, vips: VipStore) -> None:
        self._vips = vips

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        vip_record = data.get("vip_record")
        if vip_record is None:
            return await handler(event, data)

        frozen_until = getattr(vip_record, "frozen_until", None)
        if frozen_until is not None and frozen_until > datetime.now(UTC):
            user_id = getattr(getattr(event, "from_user", None), "id", None)
            logger.debug(
                "freeze_drop",
                extra={
                    "telegram_user_id": user_id,
                    "frozen_until": frozen_until.isoformat(),
                },
            )
            return None  # Silent drop

        return await handler(event, data)


__all__ = ["FreezeCheckMiddleware"]
