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

    Self-sufficient: looks up VIP by ``event.from_user.id`` via injected
    ``VipStore``. Does NOT depend on AuthMiddleware.
    Registered after ErrorHandler + Dedup + RateLimit + Logging + BC + Owner (index 6).

    Lookup failure is fail-CLOSED: log and drop (do not call handler).
    ``vip_record is None`` still passes through (non-VIP / unknown).
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

        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if user_id is None:
            return await handler(event, data)

        try:
            vip_record = await self._vips.get_by_telegram_user_id(user_id)
        except Exception:
            logger.exception(
                "freeze_check_lookup_error",
                extra={"telegram_user_id": user_id},
            )
            return None

        if vip_record is None:
            return await handler(event, data)

        # Cache the record so AuthMiddleware can reuse it.
        data["_vip_record"] = vip_record

        frozen_until = getattr(vip_record, "frozen_until", None)
        if frozen_until is not None:
            # Mirror admin/orchestrator: normalize naive datetimes before compare.
            if frozen_until.tzinfo is None:
                frozen_until = frozen_until.replace(tzinfo=UTC)
            if frozen_until > datetime.now(UTC):
                logger.debug(
                    "freeze_drop",
                    extra={
                        "telegram_user_id": user_id,
                        "frozen_until": frozen_until.isoformat(),
                    },
                )
                return None

        return await handler(event, data)


__all__ = ["FreezeCheckMiddleware"]
