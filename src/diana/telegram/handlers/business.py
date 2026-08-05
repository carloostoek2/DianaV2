"""Business message handler → TurnOrchestrator."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.types import Message

from diana.application.ports import VipInboundMessage
from diana.application.turn_orchestrator import TurnOrchestrator

logger = logging.getLogger("diana.telegram")


def build_business_router(*, orchestrator: TurnOrchestrator) -> Router:
    router = Router(name="business")

    @router.business_message()
    async def on_business_message(
        message: Message,
        business_connection_id: str | None = None,
        vip_id: UUID | None = None,
        channel_type: str = "vip",
        **_: Any,
    ) -> None:
        bc = business_connection_id or message.business_connection_id
        text = message.text or message.caption or ""
        inbound = VipInboundMessage(
            chat_id=message.chat.id,
            text=text,
            telegram_message_id=message.message_id,
            business_connection_id=bc,
            vip_id=vip_id,
            channel_type=channel_type,
        )
        try:
            turn_id = await orchestrator.handle_vip_message(inbound)
            logger.info(
                "business_handled",
                extra={"turn_id": str(turn_id), "chat_id": inbound.chat_id},
            )
        except Exception:
            logger.exception(
                "business_handler_error",
                extra={
                    "chat_id": inbound.chat_id,
                    "telegram_message_id": inbound.telegram_message_id,
                    "vip_id": str(inbound.vip_id) if inbound.vip_id else None,
                    "business_connection_id": inbound.business_connection_id,
                },
            )

    @router.edited_business_message()
    async def on_edited_business_message(
        message: Message,
        business_connection_id: str | None = None,
        vip_id: UUID | None = None,
        channel_type: str = "vip",
        **_: Any,
    ) -> None:
        bc = business_connection_id or message.business_connection_id
        text = message.text or message.caption or ""
        if not text:
            return
        inbound = VipInboundMessage(
            chat_id=message.chat.id,
            text=text,
            telegram_message_id=message.message_id,
            business_connection_id=bc,
            vip_id=vip_id,
            is_edit=True,
            channel_type=channel_type,
        )
        try:
            # Same path as new message: bumps VIP epoch → cancels in-flight
            # turn for the original text; history upsert keeps only latest text.
            turn_id = await orchestrator.handle_vip_message(inbound)
            logger.info(
                "edited_business_handled",
                extra={"turn_id": str(turn_id), "chat_id": inbound.chat_id},
            )
        except Exception:
            logger.exception(
                "edited_business_handler_error",
                extra={
                    "chat_id": inbound.chat_id,
                    "telegram_message_id": inbound.telegram_message_id,
                    "vip_id": str(inbound.vip_id) if inbound.vip_id else None,
                    "business_connection_id": inbound.business_connection_id,
                },
            )

    return router


async def handle_business_message(
    *,
    orchestrator: TurnOrchestrator,
    chat_id: int,
    text: str,
    telegram_message_id: int | None,
    business_connection_id: str | None,
    vip_id: UUID | None,
) -> UUID:
    """Pure callable used by unit tests (no aiogram Router required)."""
    inbound = VipInboundMessage(
        chat_id=chat_id,
        text=text,
        telegram_message_id=telegram_message_id,
        business_connection_id=business_connection_id,
        vip_id=vip_id,
    )
    return await orchestrator.handle_vip_message(inbound)


__all__ = ["build_business_router", "handle_business_message"]
