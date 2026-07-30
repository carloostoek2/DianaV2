"""BusinessConnection lifecycle handler — persist enable/disable events."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.types import BusinessConnection

from diana.application.ports import BusinessConnectionRecord, BusinessConnectionStore

logger = logging.getLogger("diana.telegram")


def build_business_connection_router(*, store: BusinessConnectionStore) -> Router:
    router = Router(name="business_connection")

    @router.business_connection()
    async def on_business_connection(event: BusinessConnection, **_: Any) -> None:
        try:
            record = BusinessConnectionRecord(
                business_connection_id=event.id,
                user_id=event.user.id,
                user_chat_id=event.user_chat_id,
                date=event.date,
                can_reply=event.can_reply,
                is_enabled=event.is_enabled,
            )
            await store.upsert(record)
            state = "enabled" if event.is_enabled else "disabled"
            logger.info(
                "business_connection_" + state,
                extra={
                    "business_connection_id": event.id,
                    "user_id": event.user.id,
                },
            )
        except Exception:
            logger.exception(
                "business_connection_handler_error",
                extra={
                    "business_connection_id": event.id,
                    "user_id": event.user.id,
                },
            )

    return router


__all__ = ["build_business_connection_router"]
