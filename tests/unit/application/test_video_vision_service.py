"""VideoVisionService — revisión por fotogramas + descripción (unit).

Un video no se puede tapar: si algún fotograma muestra datos fuertes o un
documento de identidad, el video no sale. Estas pruebas fijan ese contrato.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from diana.application.video_vision_service import VideoVisionService
from diana.infrastructure.vision.ocr import OcrUnavailableError
from diana.infrastructure.vision.video_frames import (
    FrameExtractionError,
    VideoFrame,
)


def _frames(count: int = 3) -> tuple[VideoFrame, ...]:
    return tuple(
        VideoFrame(png_bytes=f"png-{i}".encode(), timestamp_s=float(i))
        for i in range(count)
    )


class _FakeExtractor:
    def __init__(self, frames=None, error: Exception | None = None) -> None:
        self._frames = frames if frames is not None else _frames()
        self._error = error
        self.calls = 0

    def extract_frames(self, video_bytes):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._frames


class _FakeOcr:
    """Devuelve un texto por fotograma, en orden; el último se repite."""

    def __init__(self, texts: list[str | Exception]) -> None:
        self._texts = texts
        self.calls = 0

    def extract_text(self, image_bytes):
        index = min(self.calls, len(self._texts) - 1)
        self.calls += 1
        value = self._texts[index]
        if isinstance(value, type) and issubclass(value, Exception):
            raise value()
        return value


class _SpyDescriber:
    def __init__(self, text: str | None = "un video de dedicatoria") -> None:
        self._text = text
        self.calls = 0
        self.frames_calls = 0
        self.seen_bytes: bytes | None = None
        self.seen_mime: str | None = None
        self.seen_frames: list[bytes] | None = None

    async def describe(self, video_bytes, *, mime_type):
        self.calls += 1
        self.seen_bytes = video_bytes
        self.seen_mime = mime_type
        return self._text

    async def describe_frames(self, frames, *, mime_type):
        self.frames_calls += 1
        self.seen_frames = list(frames)
        return self._text


def _service(
    *,
    texts=None,
    frames=None,
    error=None,
    enabled=True,
    describer=None,
    send_max_bytes=1024,
    frames_to_send=20,
):
    extractor = _FakeExtractor(frames=frames, error=error)
    ocr = _FakeOcr(texts if texts is not None else [""])
    spy = describer if describer is not None else _SpyDescriber()
    service = VideoVisionService(
        frames=extractor,
        ocr=ocr,
        describer=spy,
        enabled=enabled,
        send_max_bytes=send_max_bytes,
        frames_to_send=frames_to_send,
    )
    return SimpleNamespace(service=service, extractor=extractor, ocr=ocr, spy=spy)


@pytest.mark.asyncio
async def test_clean_frames_are_described_and_video_travels() -> None:
    ctx = _service(texts=["una playa"])
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.enabled is True
    assert result.sensitive is False
    assert result.description == "un video de dedicatoria"
    assert ctx.spy.seen_bytes == b"mp4"
    assert ctx.spy.seen_mime == "video/mp4"


@pytest.mark.asyncio
async def test_every_frame_is_reviewed_before_the_video_travels() -> None:
    ctx = _service(texts=["", "", ""], frames=_frames(3))
    await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert ctx.ocr.calls == 3


@pytest.mark.asyncio
async def test_identity_document_in_any_frame_blocks_the_video() -> None:
    ctx = _service(texts=["", "documento nacional de identidad"])
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.sensitive is True
    assert result.reason == "identidad"
    assert ctx.spy.calls == 0  # nunca salió del servidor


@pytest.mark.asyncio
async def test_card_in_a_later_frame_blocks_the_video() -> None:
    """El chequeo no se queda con el primer fotograma."""
    ctx = _service(texts=["", "", "4111 1111 1111 1111"])
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.sensitive is True
    assert result.reason == "tarjeta"
    assert ctx.spy.calls == 0


@pytest.mark.asyncio
async def test_receipt_keywords_alone_do_not_block() -> None:
    """Una factura viaja: el importe es el comprobante de pago."""
    ctx = _service(texts=["factura total a pagar"])
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.sensitive is False
    assert ctx.spy.calls == 1


@pytest.mark.asyncio
async def test_frame_extraction_failure_is_fail_closed() -> None:
    ctx = _service(error=FrameExtractionError("sin fotogramas"))
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.sensitive is True
    assert result.reason == "no_verificable"
    assert ctx.spy.calls == 0


@pytest.mark.asyncio
async def test_no_frames_at_all_is_fail_closed() -> None:
    """Sin un solo fotograma no hay nada que revisar: el video no sale."""
    ctx = _service(frames=())
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.sensitive is True
    assert result.reason == "no_verificable"
    assert ctx.spy.calls == 0


@pytest.mark.asyncio
async def test_ocr_unavailable_is_fail_closed() -> None:
    ctx = _service(texts=[OcrUnavailableError])
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.sensitive is True
    assert result.reason == "no_verificable"
    assert ctx.spy.calls == 0


@pytest.mark.asyncio
async def test_disabled_service_does_nothing() -> None:
    ctx = _service(enabled=False)
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.enabled is False
    assert ctx.extractor.calls == 0
    assert ctx.ocr.calls == 0
    assert ctx.spy.calls == 0


@pytest.mark.asyncio
async def test_heavy_video_is_described_from_its_frames() -> None:
    """Un video que no entra en un solo envío no sale: salen sus cuadros."""
    ctx = _service(frames=_frames(5), send_max_bytes=4)
    result = await ctx.service.analyze(b"12345", mime_type="video/mp4")
    assert result.sensitive is False
    assert result.description == "un video de dedicatoria"
    assert ctx.spy.frames_calls == 1
    assert ctx.spy.calls == 0  # el archivo completo nunca se envía
    assert ctx.spy.seen_frames is not None and len(ctx.spy.seen_frames) == 5


@pytest.mark.asyncio
async def test_frames_sent_are_capped_but_spread() -> None:
    ctx = _service(frames=_frames(10), send_max_bytes=4, frames_to_send=4)
    await ctx.service.analyze(b"12345", mime_type="video/mp4")
    assert ctx.spy.seen_frames is not None
    assert len(ctx.spy.seen_frames) == 4


@pytest.mark.asyncio
async def test_small_video_still_travels_whole() -> None:
    ctx = _service(frames=_frames(3), send_max_bytes=1024)
    await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert ctx.spy.calls == 1
    assert ctx.spy.frames_calls == 0


@pytest.mark.asyncio
async def test_sensitive_frames_block_even_a_heavy_video() -> None:
    """La revisión local manda: si un cuadro trae datos, no sale nada."""
    ctx = _service(texts=["", "4111 1111 1111 1111"], frames=_frames(3), send_max_bytes=2)
    result = await ctx.service.analyze(b"12345", mime_type="video/mp4")
    assert result.sensitive is True
    assert result.reason == "tarjeta"
    assert ctx.spy.frames_calls == 0
    assert ctx.spy.calls == 0


@pytest.mark.asyncio
async def test_caption_failure_is_fail_open() -> None:
    """Si la descripción falla, el turno sigue con la etiqueta plana."""
    ctx = _service(describer=_SpyDescriber(text=None))
    result = await ctx.service.analyze(b"mp4", mime_type="video/mp4")
    assert result.enabled is True
    assert result.sensitive is False
    assert result.description is None
