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
from diana.application.media_text import SENSITIVE_MARK, compose_media_text
from diana.application.ports import VipInboundMessage
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.application.video_vision_service import VideoVisionService
from diana.infrastructure.vision.ocr import (
    OcrUnavailableError,
    detect_image_mime,
)
from diana.telegram.media_tags import inbound_text, media_tag

logger = logging.getLogger("diana.telegram")

MediaDownloader = Callable[[str], Awaitable[bytes]]

# Tope real de la API de Telegram para que un bot descargue un archivo. Un video
# más pesado ni siquiera se puede bajar, así que no se intenta.
_MAX_VIDEO_BYTES = 20 * 1024 * 1024
_DEFAULT_VIDEO_MIME = "video/mp4"


async def download_media_bytes(bot: Bot, file_id: str) -> bytes:
    """Descarga un archivo de Telegram en memoria (nunca se escribe en disco)."""
    file = await bot.get_file(file_id)
    if file.file_path is None:
        raise OcrUnavailableError("telegram file has no download path")
    buffer = io.BytesIO()
    await bot.download_file(file.file_path, destination=buffer)
    return buffer.getvalue()


async def _photo_text_and_id(
    message: Message,
    *,
    vision: ImageVisionService,
    downloader: MediaDownloader,
    tag: str,
    caption: str,
    plain: str,
) -> tuple[str, str | None]:
    """Describe la foto entrante → (texto, file_id para el mensaje a la dueña)."""
    file_id = message.photo[-1].file_id  # type: ignore[index]
    try:
        image_bytes = await downloader(file_id)
        mime_type = detect_image_mime(image_bytes)
        result = await vision.analyze(image_bytes, mime_type=mime_type)
    except Exception as exc:
        # Fallo de descarga, decodificación o análisis → etiqueta plana; la
        # dueña igual recibe la foto para revisarla ella misma.
        logger.warning(
            "image_vision_failed_fail_open",
            extra={"error_type": type(exc).__name__},
        )
        return plain, file_id
    return compose_media_text(result, tag=tag, caption=caption), file_id


async def _video_text(
    message: Message,
    *,
    video_vision: VideoVisionService,
    downloader: MediaDownloader,
    tag: str,
    caption: str,
    plain: str,
) -> str:
    """Describe el video entrante, o devuelve la etiqueta plana de media."""
    video = message.video or message.video_note
    if video is None:
        return plain
    declared = getattr(video, "file_size", None)
    if isinstance(declared, int) and declared > _MAX_VIDEO_BYTES:
        logger.info(
            "video_vision_skipped_too_large",
            extra={"file_size": declared},
        )
        return plain
    try:
        video_bytes = await downloader(video.file_id)
        mime_type = (getattr(video, "mime_type", None) or _DEFAULT_VIDEO_MIME).strip()
        result = await video_vision.analyze(video_bytes, mime_type=mime_type)
    except Exception as exc:
        # Fallo de descarga o de análisis → etiqueta plana (el video no viaja).
        logger.warning(
            "video_vision_failed_fail_open",
            extra={"error_type": type(exc).__name__},
        )
        return plain
    return compose_media_text(result, tag=tag, caption=caption)


async def _vision_text_and_media(
    message: Message,
    *,
    vision: ImageVisionService | None,
    video_vision: VideoVisionService | None,
    downloader: MediaDownloader,
) -> tuple[str, str | None]:
    """Describe la media entrante (o la marca sensible) → (texto, foto_file_id).

    Se llama solo cuando la visión correspondiente está encendida. Nunca
    levanta excepciones: cualquier fallo vuelve a la etiqueta plana de media.
    La foto viaja además a la dueña en el mensaje de aprobación
    (``photo_file_id``); el video todavía no. Los bytes nunca se guardan.
    """
    caption = (message.caption or "").strip()
    # Etiqueta base consciente de álbum (``imagen`` / ``imagen parte de
    # álbum``): las variantes se arman desde ella para que un miembro de álbum
    # siga siendo identificable sin importar cómo termine el análisis.
    tag = media_tag(message) or "imagen"
    plain = f"[{tag}]" if not caption else f"[{tag}] {caption}"
    if message.photo and vision is not None:
        return await _photo_text_and_id(
            message,
            vision=vision,
            downloader=downloader,
            tag=tag,
            caption=caption,
            plain=plain,
        )
    if (message.video or message.video_note) and video_vision is not None:
        text = await _video_text(
            message,
            video_vision=video_vision,
            downloader=downloader,
            tag=tag,
            caption=caption,
            plain=plain,
        )
        return text, None
    return inbound_text(message), None


def build_business_router(
    *,
    orchestrator: TurnOrchestrator,
    on_vip_inbound: Callable[[int], None] | None = None,
    image_vision: ImageVisionService | None = None,
    video_vision: VideoVisionService | None = None,
    media_downloader: MediaDownloader | None = None,
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
        text = inbound_text(message)
        photo_file_id: str | None = None
        image_on = image_vision is not None and image_vision.enabled
        video_on = video_vision is not None and video_vision.enabled
        if media_downloader is not None and (image_on or video_on):
            # Camino de visión solo con la función encendida: apagada se
            # conserva la etiqueta de media, sin descarga ni análisis
            # (regla de oro AGENTS §1).
            text, photo_file_id = await _vision_text_and_media(
                message,
                vision=image_vision if image_on else None,
                video_vision=video_vision if video_on else None,
                downloader=media_downloader,
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
    "MediaDownloader",
    "build_business_router",
    "download_media_bytes",
    "handle_business_message",
]
