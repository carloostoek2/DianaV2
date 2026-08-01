"""FreezeCheckMiddleware — VIP freeze enforcement for message handlers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.application.ports import (
    DoctrineNotification,
    GrayZoneServicePort,
    OwnerNotifierPort,
    VipStore,
)

logger = logging.getLogger("diana.telegram")

_DEFAULT_REMINDER_TTL_S = 1200.0  # 20 min


class FreezeCheckMiddleware(BaseMiddleware):
    """Drop messages from VIPs whose frozen_until > now (silent discard).

    Self-sufficient: looks up VIP by ``event.from_user.id`` via injected
    ``VipStore``. Does NOT depend on AuthMiddleware.
    Registered after ErrorHandler + Dedup + RateLimit + Logging + BC + Owner (index 6).

    Lookup failure is fail-CLOSED: log and drop (do not call handler).
    ``vip_record is None`` still passes through (non-VIP / unknown).

    When a frozen VIP with an open gray zone query sends a message, a
    reminder notification is sent to the owner with doctrine resolution
    buttons. Reminders are debounced per VIP (default 20 min).
    """

    def __init__(
        self,
        vips: VipStore,
        *,
        gray_zone: GrayZoneServicePort | None = None,
        notifier: OwnerNotifierPort | None = None,
        reminder_ttl_s: float = _DEFAULT_REMINDER_TTL_S,
    ) -> None:
        self._vips = vips
        self._gray_zone = gray_zone
        self._notifier = notifier
        self._reminder_ttl = timedelta(seconds=reminder_ttl_s)
        self._last_reminder: dict[UUID, datetime] = {}

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
                await self._maybe_notify_freeze_reminder(event, vip_record)
                return None

        return await handler(event, data)

    async def _maybe_notify_freeze_reminder(
        self, event: Message, vip_record: Any
    ) -> None:
        """Send a doctrine reminder when a frozen VIP with an open gray zone
        query sends a new message. Debounced per VIP; fail-soft so the
        drop path is never affected by notification failures."""
        if self._gray_zone is None or self._notifier is None:
            return
        if getattr(event, "edit_date", None) is not None:
            return  # edits are not new messages — don't re-nag

        vip_id = getattr(vip_record, "id", None)
        if vip_id is None:
            return

        now = datetime.now(UTC)
        last = self._last_reminder.get(vip_id)
        if last is not None and now - last < self._reminder_ttl:
            return

        try:
            query = await self._gray_zone.get_open_query_by_vip_id(vip_id)
        except Exception:
            logger.exception(
                "freeze_reminder_lookup_error",
                extra={"vip_id": str(vip_id)},
            )
            return

        if query is None:
            return

        chat = getattr(event, "chat", None)
        if chat is None or getattr(chat, "id", None) is None:
            return

        payload = DoctrineNotification(
            turn_id=query.turn_id,
            chat_id=chat.id,
            vip_text=getattr(event, "text", None) or getattr(event, "caption", None) or query.question,
            draft_text=getattr(query, "draft", None),
            evaluation_summary="",
            reason="recordatorio_zona_gris",
            business_connection_id=getattr(event, "business_connection_id", None),
        )
        try:
            await self._notifier.notify_doctrine(payload)
        except Exception:
            logger.exception(
                "freeze_reminder_failed",
                extra={
                    "vip_id": str(vip_id),
                    "turn_id": str(query.turn_id),
                },
            )
            return

        self._last_reminder[vip_id] = now
        logger.info(
            "freeze_reminder_sent",
            extra={
                "vip_id": str(vip_id),
                "turn_id": str(query.turn_id),
            },
        )


__all__ = ["FreezeCheckMiddleware"]
