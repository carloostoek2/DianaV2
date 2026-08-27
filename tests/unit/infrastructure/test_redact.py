"""Local redaction — black rectangles over OCR lines (pure image I/O, unit)."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from diana.infrastructure.vision.ocr import OcrLine
from diana.infrastructure.vision.redact import mask_lines


def _img_bytes(fmt: str = "PNG") -> bytes:
    img = Image.new("RGB", (100, 60), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 10, 70, 30], fill="red")  # content that must be hidden
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _pixels(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def test_mask_lines_paints_black_over_box_and_leaves_rest() -> None:
    original = _img_bytes()
    line = OcrLine(text="SECRETO", left=20, top=5, width=60, height=30)
    masked = mask_lines(original, [line], mime_type="image/png")

    assert masked != original
    out = _pixels(masked)
    # Inside the box (auto margin ≥ 9px covers the red block): black.
    assert out.getpixel((40, 20)) == (0, 0, 0)
    assert out.getpixel((35, 25)) == (0, 0, 0)
    # Outside the box: untouched white.
    assert out.getpixel((5, 30)) == (255, 255, 255)
    assert out.getpixel((95, 30)) == (255, 255, 255)
    assert out.getpixel((50, 55)) == (255, 255, 255)


def test_mask_lines_preserves_format() -> None:
    original = _img_bytes(fmt="JPEG")
    line = OcrLine(text="SECRETO", left=20, top=5, width=60, height=30)
    masked = mask_lines(original, [line], mime_type="image/jpeg")
    assert Image.open(io.BytesIO(masked)).format == "JPEG"


def test_mask_lines_explicit_margin() -> None:
    original = _img_bytes()
    line = OcrLine(text="SECRETO", left=30, top=10, width=40, height=20)
    # margin=0 ⇒ only the exact box is painted; red block [30,10,70,30] covered.
    masked = mask_lines(original, [line], mime_type="image/png", margin=0)
    assert _pixels(masked).getpixel((40, 20)) == (0, 0, 0)
    # One pixel outside the exact box stays white (no padding).
    assert _pixels(masked).getpixel((29, 9)) == (255, 255, 255)


def test_mask_lines_clips_at_image_edges() -> None:
    original = _img_bytes()
    line = OcrLine(text="X", left=-20, top=-20, width=200, height=120)
    masked = mask_lines(original, [line], mime_type="image/png")
    out = _pixels(masked)
    assert out.getpixel((50, 30)) == (0, 0, 0)  # box covers everything
    # And the image still decodes with the original dimensions.
    assert out.size == (100, 60)
