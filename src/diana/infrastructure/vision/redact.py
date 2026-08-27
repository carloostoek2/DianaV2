"""Local redaction — paints black rectangles over OCR lines (pure image I/O).

This module is pure infrastructure: it knows nothing about privacy rules,
Gemini or the business. Given an image and the OCR line boxes to hide, it
returns re-encoded bytes with those regions painted opaque black. The privacy
DECISION (which lines hide) lives in the application layer; here only the
mechanics run. The masked bytes are ephemeral — nothing is written to disk.

The margin around each box absorbs anti-aliasing so no pixel of the hidden
text survives at the edges.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw

from diana.infrastructure.vision.ocr import OcrLine, pil_format_for_mime

# Extra padding around each line box (fraction of the line height, plus a
# floor in px) so glyph fringes / anti-aliasing never leak a readable pixel.
_MARGIN_RATIO = 0.3
_MIN_MARGIN_PX = 4


def mask_lines(
    image_bytes: bytes,
    lines: Sequence[OcrLine],
    *,
    mime_type: str | None = None,
    margin: int | None = None,
) -> bytes:
    """Return re-encoded image bytes with the given OCR lines painted black.

    ``margin`` (px) defaults to per-line auto padding (see module constants).
    The output is encoded in the same format as the input (or PNG when the
    format cannot be determined), so the declared MIME stays truthful.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        canvas = img.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        for line in lines:
            pad = margin if margin is not None else _line_margin(line)
            x1 = max(0, line.left - pad)
            y1 = max(0, line.top - pad)
            x2 = min(canvas.width, line.right + pad)
            y2 = min(canvas.height, line.bottom + pad)
            if x1 >= x2 or y1 >= y2:
                continue  # box fully outside the visible area — nothing to paint
            draw.rectangle([x1, y1, x2, y2], fill="black")
        fmt = pil_format_for_mime(mime_type) or img.format or "PNG"
        buf = io.BytesIO()
        canvas.save(buf, format=fmt)
        return buf.getvalue()


def _line_margin(line: OcrLine) -> int:
    return max(_MIN_MARGIN_PX, round(line.height * _MARGIN_RATIO))


__all__ = ["mask_lines"]
