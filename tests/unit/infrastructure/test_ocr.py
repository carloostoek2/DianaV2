"""Local OCR — language fallback, mime detection, real-tesseract smoke."""

from __future__ import annotations

import io
import shutil
import sys
from types import ModuleType

import pytest
from PIL import Image, ImageDraw, ImageFont

from diana.infrastructure.vision.ocr import (
    OcrEngine,
    OcrUnavailableError,
    detect_image_mime,
)


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


def _text_png_bytes() -> bytes:
    """A small image with clear digits (tesseract reads these reliably)."""
    img = Image.new("RGB", (640, 120), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40
        )
    except Exception:  # pragma: no cover - fontless host
        font = ImageFont.load_default()
    d.text((20, 35), "FACTURA 1234 TOTAL 99.90", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_detect_image_mime_png() -> None:
    assert detect_image_mime(_png_bytes()) == "image/png"


def test_detect_image_mime_rejects_garbage() -> None:
    with pytest.raises(OcrUnavailableError):
        detect_image_mime(b"not-an-image")


def test_lang_fallback_to_eng_when_pack_missing(monkeypatch) -> None:
    """spa+eng requested but spa missing ⇒ retry with plain eng (never dies)."""
    calls: list[str] = []

    class FakeTesseract:
        @staticmethod
        def image_to_string(img, lang):  # noqa: ARG004
            calls.append(lang)
            if lang == "spa+eng":
                raise Exception("Failed loading language 'spa'")
            return "hola 1234"

    monkeypatch.setitem(sys.modules, "pytesseract", ModuleType("pytesseract"))
    sys.modules["pytesseract"].image_to_string = FakeTesseract.image_to_string
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    engine = OcrEngine()
    text = engine.extract_text(_png_bytes())
    assert calls == ["spa+eng", "eng"]
    assert "1234" in text


def test_eng_only_failure_is_ocr_unavailable(monkeypatch) -> None:
    """When even eng fails, the error surfaces as OcrUnavailableError."""
    calls: list[str] = []

    class FakeTesseract:
        @staticmethod
        def image_to_string(img, lang):  # noqa: ARG004
            calls.append(lang)
            raise Exception("tesseract broken")

    monkeypatch.setitem(sys.modules, "pytesseract", ModuleType("pytesseract"))
    sys.modules["pytesseract"].image_to_string = FakeTesseract.image_to_string
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    engine = OcrEngine()
    with pytest.raises(OcrUnavailableError):
        engine.extract_text(_png_bytes())
    assert calls == ["spa+eng", "eng"]


@pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract not installed"
)
def test_real_ocr_reads_digits() -> None:
    """End-to-end with the real tesseract binary (spa+eng or eng fallback)."""
    engine = OcrEngine()
    text = engine.extract_text(_text_png_bytes())
    assert "1234" in text
