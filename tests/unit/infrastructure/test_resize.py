"""downscale_image — local pre-Gemini downscale (pure image I/O)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from diana.infrastructure.vision.resize import downscale_image


def _image_bytes(width: int, height: int, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format=fmt)
    return buf.getvalue()


def test_small_image_returns_none() -> None:
    assert downscale_image(_image_bytes(1280, 800)) is None


def test_exactly_at_limit_returns_none() -> None:
    assert downscale_image(_image_bytes(1280, 1280)) is None


def test_large_image_downscaled_to_jpeg() -> None:
    result = downscale_image(_image_bytes(4000, 3000))
    assert result is not None
    with Image.open(io.BytesIO(result)) as img:
        assert img.format == "JPEG"
        assert max(img.width, img.height) <= 1280
        # Aspect ratio preserved: 4000x3000 → 1280x960.
        assert (img.width, img.height) == (1280, 960)


def test_undecodable_bytes_returns_none() -> None:
    assert downscale_image(b"not an image") is None


def test_portrait_large_image_preserves_ratio() -> None:
    result = downscale_image(_image_bytes(1000, 3000))
    assert result is not None
    with Image.open(io.BytesIO(result)) as img:
        assert max(img.width, img.height) <= 1280
        assert (img.width, img.height) == (427, 1280)


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP", "BMP"])
def test_any_input_format_is_reencoded_to_jpeg(fmt: str) -> None:
    result = downscale_image(_image_bytes(2000, 1000, fmt=fmt))
    assert result is not None
    with Image.open(io.BytesIO(result)) as img:
        assert img.format == "JPEG"
