"""Business handler + media vision — tag replacement, photo forwarding, video."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, PhotoSize, User, Video, VideoNote
from PIL import Image

from diana.application.image_vision_service import ImageVisionResult
from diana.application.ports import VipInboundMessage
from diana.application.video_vision_service import VideoVisionResult
from diana.telegram.handlers.business import build_business_router


def _png_bytes() -> bytes:
    """A real 4x4 PNG so detect_image_mime accepts the payload."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


def _photo_message(*, caption: str | None = None) -> Message:
    return Message(
        message_id=8,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=111, is_bot=False, first_name="Vip"),
        photo=[
            PhotoSize(file_id="small", file_unique_id="u1", width=10, height=10),
            PhotoSize(file_id="big", file_unique_id="u2", width=200, height=200),
        ],
        caption=caption,
        business_connection_id="bc-1",
    )


def _album_photo_message(*, caption: str | None = None) -> Message:
    """A photo that is one member of an album (media_group_id present)."""
    return Message(
        message_id=9,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=111, is_bot=False, first_name="Vip"),
        media_group_id="grp-1",
        photo=[
            PhotoSize(file_id="small", file_unique_id="u1", width=10, height=10),
            PhotoSize(file_id="big", file_unique_id="u2", width=200, height=200),
        ],
        caption=caption,
        business_connection_id="bc-1",
    )


def _video_message(
    *,
    caption: str | None = None,
    file_size: int | None = 2_000_000,
    mime_type: str | None = "video/mp4",
) -> Message:
    return Message(
        message_id=10,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=111, is_bot=False, first_name="Vip"),
        video=Video(
            file_id="vid-big",
            file_unique_id="v1",
            width=640,
            height=360,
            duration=12,
            file_size=file_size,
            mime_type=mime_type,
        ),
        caption=caption,
        business_connection_id="bc-1",
    )


def _video_note_message() -> Message:
    return Message(
        message_id=11,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=111, is_bot=False, first_name="Vip"),
        video_note=VideoNote(
            file_id="round-1",
            file_unique_id="v2",
            length=240,
            duration=8,
            file_size=1_500_000,
        ),
        business_connection_id="bc-1",
    )


def _text_message() -> Message:
    return Message(
        message_id=7,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=111, is_bot=False, first_name="Vip"),
        text="hola vip",
        business_connection_id="bc-1",
    )


class _FakeVision:
    """ImageVisionService double with a scripted analyze()."""

    def __init__(self, result: ImageVisionResult, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.analyze = AsyncMock(return_value=result)


class _FakeVideoVision:
    """VideoVisionService double with a scripted analyze()."""

    def __init__(self, result: VideoVisionResult, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.analyze = AsyncMock(return_value=result)


def _router(vision=None, downloader=None, video_vision=None):
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(
        orchestrator=orch,
        image_vision=vision,
        video_vision=video_vision,
        media_downloader=downloader,
    )
    return orch, router.business_message.handlers[0].callback


async def _run(message, vision, downloader, video_vision=None) -> VipInboundMessage:
    orch, on_business = _router(vision, downloader, video_vision)
    await on_business(message)
    orch.handle_vip_message.assert_awaited_once()
    return orch.handle_vip_message.await_args.args[0]


@pytest.mark.asyncio
async def test_photo_with_caption_gets_caption_tag_and_file_id() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="una foto del plato")
    )
    downloader = AsyncMock(return_value=_png_bytes())
    inbound = await _run(_photo_message(caption="mira"), vision, downloader)
    assert inbound.text == "[imagen: una foto del plato] mira"
    assert inbound.photo_file_id == "big"  # largest PhotoSize
    downloader.assert_awaited_once_with("big")
    vision.analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_photo_without_caption_gets_caption_tag() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="una captura")
    )
    downloader = AsyncMock(return_value=_png_bytes())
    inbound = await _run(_photo_message(), vision, downloader)
    assert inbound.text == "[imagen: una captura]"
    assert inbound.photo_file_id == "big"


@pytest.mark.asyncio
async def test_sensitive_photo_never_calls_captioner_and_marks_tag() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=True, reason="factura")
    )
    downloader = AsyncMock(return_value=_png_bytes())
    inbound = await _run(_photo_message(caption="adjunto"), vision, downloader)
    assert (
        inbound.text
        == "[imagen] ⚠️ contiene información sensible (no analizada) adjunto"
    )
    assert inbound.photo_file_id == "big"
    # The photo still reaches the owner DM — only the caption was suppressed.


@pytest.mark.asyncio
async def test_album_photo_described_keeps_album_mark() -> None:
    """An album member stays identifiable as such after being described."""
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="una playa")
    )
    downloader = AsyncMock(return_value=_png_bytes())
    inbound = await _run(_album_photo_message(), vision, downloader)
    assert inbound.text == "[imagen parte de álbum: una playa]"


@pytest.mark.asyncio
async def test_album_sensitive_photo_keeps_album_mark() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=True, reason="factura")
    )
    downloader = AsyncMock(return_value=_png_bytes())
    inbound = await _run(_album_photo_message(), vision, downloader)
    assert (
        inbound.text
        == "[imagen parte de álbum] ⚠️ contiene información sensible (no analizada)"
    )
    assert inbound.photo_file_id == "big"


@pytest.mark.asyncio
async def test_album_photo_fail_open_keeps_album_mark() -> None:
    """With vision unavailable the tag is all the model gets — album included."""
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="x")
    )
    downloader = AsyncMock(side_effect=RuntimeError("telegram down"))
    inbound = await _run(_album_photo_message(), vision, downloader)
    assert inbound.text == "[imagen parte de álbum]"
    assert inbound.photo_file_id == "big"


@pytest.mark.asyncio
async def test_download_failure_falls_back_to_plain_tag_keeps_photo() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="x")
    )
    downloader = AsyncMock(side_effect=RuntimeError("telegram down"))
    inbound = await _run(_photo_message(), vision, downloader)
    assert inbound.text == "[imagen]"
    assert inbound.photo_file_id == "big"  # owner still reviews it herself


@pytest.mark.asyncio
async def test_analyze_failure_falls_back_to_plain_tag() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="x")
    )
    vision.analyze = AsyncMock(side_effect=RuntimeError("boom"))
    downloader = AsyncMock(return_value=_png_bytes())
    inbound = await _run(_photo_message(), vision, downloader)
    assert inbound.text == "[imagen]"


@pytest.mark.asyncio
async def test_feature_disabled_keeps_today_behavior_and_no_download() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=False), enabled=False
    )
    downloader = AsyncMock(return_value=_png_bytes())
    inbound = await _run(_photo_message(caption="mira"), vision, downloader)
    assert inbound.text == "[imagen] mira"
    assert inbound.photo_file_id is None
    downloader.assert_not_awaited()
    vision.analyze.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_vision_service_keeps_today_behavior() -> None:
    downloader = AsyncMock(return_value=_png_bytes())
    orch, on_business = _router(None, downloader)
    await on_business(_photo_message(caption="mira"))
    orch.handle_vip_message.assert_awaited_once()
    inbound = orch.handle_vip_message.await_args.args[0]
    assert inbound.text == "[imagen] mira"
    assert inbound.photo_file_id is None
    downloader.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_message_unaffected_by_vision() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="x")
    )
    downloader = AsyncMock(return_value=_png_bytes())
    inbound = await _run(_text_message(), vision, downloader)
    assert inbound.text == "hola vip"
    assert inbound.photo_file_id is None
    downloader.assert_not_awaited()


@pytest.mark.asyncio
async def test_edited_photo_path_applies_vision_and_keeps_edit_flag() -> None:
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="nueva foto")
    )
    downloader = AsyncMock(return_value=_png_bytes())
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(
        orchestrator=orch,
        image_vision=vision,
        media_downloader=downloader,
    )
    on_edited = router.edited_business_message.handlers[0].callback
    await on_edited(_photo_message(caption="nueva"))
    orch.handle_vip_message.assert_awaited_once()
    inbound = orch.handle_vip_message.await_args.args[0]
    assert inbound.text == "[imagen: nueva foto] nueva"
    assert inbound.is_edit is True
    assert inbound.photo_file_id == "big"


# --- Video ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_described_gets_video_tag() -> None:
    video_vision = _FakeVideoVision(
        VideoVisionResult(enabled=True, sensitive=False, description="una dedicatoria")
    )
    downloader = AsyncMock(return_value=b"mp4-bytes")
    inbound = await _run(_video_message(), None, downloader, video_vision)
    assert inbound.text == "[video: una dedicatoria]"
    # El video todavía no viaja al mensaje de aprobación de la dueña.
    assert inbound.photo_file_id is None
    downloader.assert_awaited_once_with("vid-big")
    video_vision.analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_video_with_caption_keeps_caption_after_description() -> None:
    video_vision = _FakeVideoVision(
        VideoVisionResult(enabled=True, sensitive=False, description="un collage")
    )
    downloader = AsyncMock(return_value=b"mp4-bytes")
    inbound = await _run(
        _video_message(caption="mira esto"), None, downloader, video_vision
    )
    assert inbound.text == "[video: un collage] mira esto"


@pytest.mark.asyncio
async def test_sensitive_video_is_marked_and_never_described() -> None:
    video_vision = _FakeVideoVision(
        VideoVisionResult(enabled=True, sensitive=True, reason="tarjeta")
    )
    downloader = AsyncMock(return_value=b"mp4-bytes")
    inbound = await _run(_video_message(), None, downloader, video_vision)
    assert (
        inbound.text == "[video] ⚠️ contiene información sensible (no analizada)"
    )


@pytest.mark.asyncio
async def test_video_note_uses_the_same_video_tag() -> None:
    video_vision = _FakeVideoVision(
        VideoVisionResult(enabled=True, sensitive=False, description="un saludo")
    )
    downloader = AsyncMock(return_value=b"mp4-bytes")
    inbound = await _run(_video_note_message(), None, downloader, video_vision)
    assert inbound.text == "[video: un saludo]"
    downloader.assert_awaited_once_with("round-1")


@pytest.mark.asyncio
async def test_oversized_video_is_not_downloaded() -> None:
    """Más de 20 MB no se puede bajar: se conserva la etiqueta plana."""
    video_vision = _FakeVideoVision(
        VideoVisionResult(enabled=True, sensitive=False, description="x")
    )
    downloader = AsyncMock(return_value=b"mp4-bytes")
    inbound = await _run(
        _video_message(file_size=25 * 1024 * 1024), None, downloader, video_vision
    )
    assert inbound.text == "[video]"
    downloader.assert_not_awaited()
    video_vision.analyze.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_download_failure_falls_back_to_plain_tag() -> None:
    video_vision = _FakeVideoVision(
        VideoVisionResult(enabled=True, sensitive=False, description="x")
    )
    downloader = AsyncMock(side_effect=RuntimeError("telegram down"))
    inbound = await _run(_video_message(), None, downloader, video_vision)
    assert inbound.text == "[video]"


@pytest.mark.asyncio
async def test_video_vision_disabled_keeps_plain_tag_and_no_download() -> None:
    video_vision = _FakeVideoVision(
        VideoVisionResult(enabled=False), enabled=False
    )
    downloader = AsyncMock(return_value=b"mp4-bytes")
    inbound = await _run(_video_message(caption="hola"), None, downloader, video_vision)
    assert inbound.text == "[video] hola"
    assert inbound.photo_file_id is None
    downloader.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_with_image_vision_only_stays_plain() -> None:
    """Con visión de fotos encendida y la de video apagada, el video no se toca."""
    vision = _FakeVision(
        ImageVisionResult(enabled=True, sensitive=False, description="x")
    )
    downloader = AsyncMock(return_value=b"mp4-bytes")
    inbound = await _run(_video_message(), vision, downloader, None)
    assert inbound.text == "[video]"
    downloader.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_video_mime_defaults_to_mp4() -> None:
    video_vision = _FakeVideoVision(
        VideoVisionResult(enabled=True, sensitive=False, description="x")
    )
    downloader = AsyncMock(return_value=b"mp4-bytes")
    await _run(_video_message(mime_type=None), None, downloader, video_vision)
    assert video_vision.analyze.await_args.kwargs["mime_type"] == "video/mp4"
