"""Business message handler → TurnOrchestrator."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.types import Message

from diana.application.ports import VipInboundMessage
from diana.application.turn_orchestrator import TurnOrchestrator

logger = logging.getLogger("diana.telegram")

# Content types that carry no text: the model sees only the tag so it knows a
# file was sent. A message has exactly one content type, so order is cosmetic.
_MEDIA_TAGS: tuple[tuple[str, str], ...] = (
    ("photo", "imagen"),
    ("video", "video"),
    ("audio", "audio"),
    ("voice", "voz"),
    ("video_note", "video"),
    ("document", "documento"),
    ("animation", "gif"),
    ("sticker", "sticker"),
)


def _inbound_text(message: Message) -> str:
    """Text for the inbound DTO; media sends get a visible type tag.

    A media message without caption has neither ``text`` nor ``caption``, so
    the model would otherwise see an empty message. Tag the type and keep the
    caption (if any) after the tag.
    """
    for kind, tag in _MEDIA_TAGS:
        if getattr(message, kind) is not None:
            caption = (message.caption or "").strip()
            return f"[{tag}]" if not caption else f"[{tag}] {caption}"
    return message.text or message.caption or ""


def build_business_router(
    *,
    orchestrator: TurnOrchestrator,
    on_vip_inbound: Callable[[int], None] | None = None,
) -> Router:
    router = Router(name="business")

    def _notify_inbound(chat_id: int) -> None:
        if on_vip_inbound is None:
            return
        try:
            on_vip_inbound(chat_id)
        except Exception:
            logger.exception(
                "vip_inbound_hook_failed", extra={"chat_id": chat_id}
            )

    @router.business_message()
    async def on_business_message(
        message: Message,
        business_connection_id: str | None = None,
        vip_id: UUID | None = None,
        channel_type: str = "vip",
        atencion_limit_counted: bool = False,
        **_: Any,
    ) -> None:
        bc = business_connection_id or message.business_connection_id
        text = _inbound_text(message)
        inbound = VipInboundMessage(
            chat_id=message.chat.id,
            text=text,
            telegram_message_id=message.message_id,
            business_connection_id=bc,
            vip_id=vip_id,
            channel_type=channel_type,
            counts_toward_limit=atencion_limit_counted,
        )
        _notify_inbound(inbound.chat_id)
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
        atencion_limit_counted: bool = False,
        **_: Any,
    ) -> None:
        bc = business_connection_id or message.business_connection_id
        text = _inbound_text(message)
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
            counts_toward_limit=atencion_limit_counted,
        )
        _notify_inbound(inbound.chat_id)
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
    counts_toward_limit: bool = False,
) -> UUID:
    """Pure callable used by unit tests (no aiogram Router required)."""
    inbound = VipInboundMessage(
        chat_id=chat_id,
        text=text,
        telegram_message_id=telegram_message_id,
        business_connection_id=business_connection_id,
        vip_id=vip_id,
        counts_toward_limit=counts_toward_limit,
    )
    return await orchestrator.handle_vip_message(inbound)


__all__ = ["build_business_router", "handle_business_message"]
