"""Business message handler → TurnOrchestrator."""

from __future__ import annotations

import io
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from aiogram import Bot, Router
from aiogram.types import Message

from diana.application.image_vision_service import ImageVisionService
from diana.application.ports import VipInboundMessage
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.infrastructure.vision.ocr import (
    OcrUnavailableError,
    detect_image_mime,
)

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

# Marker replacing the plain tag when the local filter flagged the image as
# sensitive: it never went to Gemini and the owner reviews it manually.
_SENSITIVE_TAG = "[imagen] ⚠️ contiene información sensible (no analizada)"


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


PhotoDownloader = Callable[[str], Awaitable[bytes]]


async def download_photo_bytes(bot: Bot, file_id: str) -> bytes:
    """Download a Telegram photo into memory (never persisted to disk)."""
    file = await bot.get_file(file_id)
    if file.file_path is None:
        raise OcrUnavailableError("telegram file has no download path")
    buffer = io.BytesIO()
    await bot.download_file(file.file_path, destination=buffer)
    return buffer.getvalue()


async def _vision_text_and_photo(
    message: Message,
    *,
    vision: ImageVisionService,
    downloader: PhotoDownloader,
) -> tuple[str, str | None]:
    """Describe an inbound photo (or mark it sensitive) → (text, photo_file_id).

    Only called when the vision feature is enabled. Never raises: any failure
    falls back to the plain media tag while still forwarding the photo to the
    owner approval DM (``photo_file_id``). The image bytes are never stored.
    """
    photo = message.photo
    caption = (message.caption or "").strip()
    plain = "[imagen]" if not caption else f"[imagen] {caption}"
    if not photo:
        return _inbound_text(message), None
    file_id = photo[-1].file_id
    try:
        image_bytes = await downloader(file_id)
        mime_type = detect_image_mime(image_bytes)
        result = await vision.analyze(
            image_bytes, mime_type=mime_type
        )
    except Exception as exc:
        # Download / decode / analysis failure → fail-open to the plain tag;
        # the owner still receives the photo to review it herself.
        logger.warning(
            "image_vision_failed_fail_open",
            extra={"error_type": type(exc).__name__},
        )
        return plain, file_id

    if not result.enabled:
        return plain, file_id
    if result.sensitive:
        text = _SENSITIVE_TAG
    elif result.description:
        text = f"[imagen: {result.description}]"
    else:
        text = "[imagen]"
    if caption:
        text = f"{text} {caption}"
    return text, file_id


def build_business_router(
    *,
    orchestrator: TurnOrchestrator,
    on_vip_inbound: Callable[[int], None] | None = None,
    image_vision: ImageVisionService | None = None,
    photo_downloader: PhotoDownloader | None = None,
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

    async def _build_inbound(
        message: Message,
        *,
        is_edit: bool,
        channel_type: str,
        atencion_limit_counted: bool,
        business_connection_id: str | None,
        vip_id: UUID | None,
    ) -> VipInboundMessage:
        text = _inbound_text(message)
        photo_file_id: str | None = None
        if image_vision is not None and image_vision.enabled:
            # Vision path only when the feature is ON: OFF keeps today's plain
            # media tag byte-for-byte (regla de oro AGENTS §1).
            if photo_downloader is not None:
                text, photo_file_id = await _vision_text_and_photo(
                    message, vision=image_vision, downloader=photo_downloader
                )
        return VipInboundMessage(
            chat_id=message.chat.id,
            text=text,
            telegram_message_id=message.message_id,
            business_connection_id=business_connection_id,
            vip_id=vip_id,
            is_edit=is_edit,
            channel_type=channel_type,
            counts_toward_limit=atencion_limit_counted,
            photo_file_id=photo_file_id,
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
        inbound = await _build_inbound(
            message,
            is_edit=False,
            channel_type=channel_type,
            atencion_limit_counted=atencion_limit_counted,
            business_connection_id=bc,
            vip_id=vip_id,
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
        inbound = await _build_inbound(
            message,
            is_edit=True,
            channel_type=channel_type,
            atencion_limit_counted=atencion_limit_counted,
            business_connection_id=bc,
            vip_id=vip_id,
        )
        if not inbound.text:
            return
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
    photo_file_id: str | None = None,
) -> UUID:
    """Pure callable used by unit tests (no aiogram Router required)."""
    inbound = VipInboundMessage(
        chat_id=chat_id,
        text=text,
        telegram_message_id=telegram_message_id,
        business_connection_id=business_connection_id,
        vip_id=vip_id,
        counts_toward_limit=counts_toward_limit,
        photo_file_id=photo_file_id,
    )
    return await orchestrator.handle_vip_message(inbound)


__all__ = [
    "PhotoDownloader",
    "build_business_router",
    "download_photo_bytes",
    "handle_business_message",
]
