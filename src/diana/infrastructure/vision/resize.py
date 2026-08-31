"""Local downscale — shrinks large images before the external caption call.

Pure infrastructure: it knows nothing about privacy rules, Gemini or the
business. Given image bytes it returns a JPEG no larger than ``max_dim`` on the
longest edge, or ``None`` when the image is already small enough to travel
as-is (or cannot be decoded — the caller keeps the original, fail-open).
"""

from __future__ import annotations

import io

from PIL import Image

# Largest edge (px) sent to the external vision provider. Enough to caption a
# scene while keeping the base64 payload small: full-res phone photos (e.g.
# 4000x3000) exceeded Gemini's read timeout on the 15s budget.
_DEFAULT_MAX_DIM = 1280
_DEFAULT_JPEG_QUALITY = 82


def downscale_image(
    image_bytes: bytes,
    *,
    max_dim: int = _DEFAULT_MAX_DIM,
    quality: int = _DEFAULT_JPEG_QUALITY,
) -> bytes | None:
    """Return downscaled JPEG bytes, or None when the image can travel as-is.

    None means "send the original": the image is already within ``max_dim`` or
    cannot be decoded — never raises, the caller decides the fallback.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.width <= max_dim and img.height <= max_dim:
                return None
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
    except Exception:
        return None


__all__ = ["downscale_image"]
