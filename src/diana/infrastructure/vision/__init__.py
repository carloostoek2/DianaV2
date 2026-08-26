"""Image processing infrastructure (OCR). No business or cognitive logic."""

from diana.infrastructure.vision.ocr import (
    OcrEngine,
    OcrUnavailableError,
    extract_text_with_pytesseract,
)

__all__ = [
    "OcrEngine",
    "OcrUnavailableError",
    "extract_text_with_pytesseract",
]
