"""Local OCR — language fallback, mime detection, real-tesseract smoke."""

from __future__ import annotations

import io
import importlib
import shutil
import sys
from types import ModuleType

import pytest
from PIL import Image, ImageDraw, ImageFont

from diana.infrastructure.vision.ocr import (
    OcrEngine,
    OcrUnavailableError,
    detect_image_mime,
    extract_lines_with_pytesseract,
    pil_format_for_mime,
)

_REAL_OCR_UNAVAILABLE = shutil.which("tesseract") is None or (
    importlib.util.find_spec("pytesseract") is None
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
    _REAL_OCR_UNAVAILABLE, reason="tesseract binary or pytesseract not installed"
)
def test_real_ocr_reads_digits() -> None:
    """End-to-end with the real tesseract binary (spa+eng or eng fallback)."""
    engine = OcrEngine()
    text = engine.extract_text(_text_png_bytes())
    assert "1234" in text


def test_pil_format_for_mime() -> None:
    assert pil_format_for_mime("image/png") == "PNG"
    assert pil_format_for_mime("image/jpeg") == "JPEG"
    assert pil_format_for_mime(None) is None
    assert pil_format_for_mime("application/pdf") is None


def _fake_data_dict() -> dict:
    """image_to_data DICT shape: two words on line (1,1), one empty word."""
    return {
        "level": [5, 5, 5],
        "page_num": [1, 1, 1],
        "block_num": [1, 1, 1],
        "par_num": [1, 1, 1],
        "line_num": [1, 1, 2],
        "word_num": [1, 2, 1],
        "left": [10, 120, 10],
        "top": [5, 7, 40],
        "width": [100, 90, 60],
        "height": [20, 18, 16],
        "conf": [90, 95, -1],
        "text": ["HOLA", "1234", ""],
    }


def test_extract_lines_groups_words_and_unions_boxes(monkeypatch) -> None:
    """Word boxes come back grouped per line with the union box (redaction)."""

    class FakeTesseract:
        class Output:
            DICT = 13

        @staticmethod
        def image_to_data(img, lang, output_type):  # noqa: ARG004
            assert output_type == FakeTesseract.Output.DICT
            return _fake_data_dict()

    monkeypatch.setitem(sys.modules, "pytesseract", ModuleType("pytesseract"))
    sys.modules["pytesseract"].image_to_data = FakeTesseract.image_to_data
    sys.modules["pytesseract"].Output = FakeTesseract.Output
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    lines = extract_lines_with_pytesseract(_png_bytes())
    assert len(lines) == 1  # the empty low-conf word is dropped
    line = lines[0]
    assert line.text == "HOLA 1234"
    assert (line.left, line.top) == (10, 5)  # min over words
    assert (line.width, line.height) == (200, 20)  # union box
    assert len(line.words) == 2


def test_extract_lines_lang_fallback(monkeypatch) -> None:
    """spa missing ⇒ retry with eng; boxes still extracted (never dies)."""
    calls: list[str] = []

    class FakeTesseract:
        class Output:
            DICT = 13

        @staticmethod
        def image_to_data(img, lang, output_type):  # noqa: ARG004
            calls.append(lang)
            if lang == "spa+eng":
                raise Exception("Failed loading language 'spa'")
            return _fake_data_dict()

    monkeypatch.setitem(sys.modules, "pytesseract", ModuleType("pytesseract"))
    sys.modules["pytesseract"].image_to_data = FakeTesseract.image_to_data
    sys.modules["pytesseract"].Output = FakeTesseract.Output
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    lines = extract_lines_with_pytesseract(_png_bytes())
    assert calls == ["spa+eng", "eng"]
    assert lines and lines[0].text == "HOLA 1234"


@pytest.mark.skipif(
    _REAL_OCR_UNAVAILABLE, reason="tesseract binary or pytesseract not installed"
)
def test_real_ocr_lines_carry_boxes() -> None:
    """End-to-end: real tesseract returns line text + a sane pixel box."""
    lines = extract_lines_with_pytesseract(_text_png_bytes())
    assert lines
    assert any("1234" in line.text for line in lines)
    assert all(line.width > 0 and line.height > 0 for line in lines)
