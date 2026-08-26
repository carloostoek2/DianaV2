"""Business handler + image vision — tag replacement and photo forwarding."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, PhotoSize, User
from PIL import Image

from diana.application.image_vision_service import ImageVisionResult
from diana.application.ports import VipInboundMessage
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

    async def analyze(self, *args, **kwargs) -> ImageVisionResult:
        return await self.analyze.analyze(*args, **kwargs) if False else self.analyze()


def _router(vision, downloader):
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(
        orchestrator=orch,
        image_vision=vision,
        photo_downloader=downloader,
    )
    return orch, router.business_message.handlers[0].callback


async def _run(message, vision, downloader) -> VipInboundMessage:
    orch, on_business = _router(vision, downloader)
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
        photo_downloader=downloader,
    )
    on_edited = router.edited_business_message.handlers[0].callback
    await on_edited(_photo_message(caption="nueva"))
    orch.handle_vip_message.assert_awaited_once()
    inbound = orch.handle_vip_message.await_args.args[0]
    assert inbound.text == "[imagen: nueva foto] nueva"
    assert inbound.is_edit is True
    assert inbound.photo_file_id == "big"
