"""Local OCR (tesseract) — reads text out of an image without leaving the box.

This module is pure infrastructure: it knows nothing about privacy rules,
Gemini, Telegram or the business. The privacy decision (sensitive or not)
lives in the application layer; this module only extracts text and images.

The tesseract binary must be installed on the host (apt: ``tesseract-ocr``;
add ``tesseract-ocr-spa`` for better Spanish). Language data is looked up in
this order: ``TESSDATA_PREFIX`` env var → the repo's ``runtime/tessdata/``
directory (installed locally when the host FS is read-only, e.g. containers)
→ ``~/.tessdata`` → the system install. Default languages are ``spa+eng`` with
an automatic fallback to ``eng`` when a requested pack is missing, so OCR
never dies on a host that only has the English pack.

``pytesseract`` is imported lazily so importing this module never fails on a
host without it — the error surfaces only when extraction is actually
attempted, as ``OcrUnavailableError``, which callers treat as "cannot verify ⇒
treat as sensitive" (fail-closed).
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from pathlib import Path

from PIL import Image

# Standard MIME types PIL can map for the formats Telegram normally delivers.
_MIME_BY_FORMAT: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}

# Default languages: Spanish first (better accents/invoices), English fallback.
# ``eng`` alone always works — digits are universal and latin text is readable.
_DEFAULT_LANGS = "spa+eng"
_FALLBACK_LANGS = "eng"

_MAX_OCR_IMAGE_PIXELS = 4000 * 4000  # guard against decompression bombs

# Repo-local language data (runtime/tessdata, gitignored) — installed when the
# host filesystem is read-only so the container keeps spa+eng working.
_REPO_TESSDATA = Path(__file__).resolve().parents[3] / "runtime" / "tessdata"
_HOME_TESSDATA = Path.home() / ".tessdata"


class OcrUnavailableError(RuntimeError):
    """OCR cannot run on this host (tesseract missing/broken) or on this image.

    Callers must treat this as "cannot verify" ⇒ sensitive (fail-closed): an
    image we cannot read locally must never be sent to an external provider.
    """


def _tessdata_dir() -> Path | None:
    """Resolve the tessdata directory, or None when only the system install exists."""
    env_dir = os.environ.get("TESSDATA_PREFIX")
    candidates = [Path(env_dir)] if env_dir else []
    candidates += [_REPO_TESSDATA, _HOME_TESSDATA]
    for candidate in candidates:
        try:
            if candidate.is_dir() and any(
                candidate.glob("*.traineddata")
            ):
                return candidate
        except OSError:  # pragma: no cover - unreadable path
            continue
    return None


def _ensure_tessdata_env() -> None:
    """Point tesseract at local language data when the host FS is read-only.

    TESSDATA_PREFIX replaces (not augments) the system tessdata dir, so the
    local dir must be self-contained (spa + eng). Only set when not already
    configured by the operator.
    """
    if os.environ.get("TESSDATA_PREFIX"):
        return
    local = _tessdata_dir()
    if local is not None:
        os.environ["TESSDATA_PREFIX"] = str(local)


def detect_image_mime(image_bytes: bytes) -> str:
    """Return the MIME type of an image payload (defaults to image/jpeg).

    Raises ``OcrUnavailableError`` when the payload is not a readable image —
    the caller should then treat the message as unverifiable.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            fmt = (img.format or "").upper()
    except Exception as exc:  # PIL raises a broad family of decode errors
        raise OcrUnavailableError(f"unreadable image payload: {type(exc).__name__}") from exc
    return _MIME_BY_FORMAT.get(fmt, "image/jpeg")


def extract_text_with_pytesseract(
    image_bytes: bytes,
    *,
    langs: str = _DEFAULT_LANGS,
) -> str:
    """Run tesseract over the image and return the extracted text.

    Pure function with a stable signature so tests can inject a fake in place
    of it. Falls back to ``eng`` when a requested language pack is missing on
    the host. Raises ``OcrUnavailableError`` when tesseract itself is missing
    or the image cannot be processed — never returns partial junk silently.
    """
    try:
        import pytesseract  # lazy: module import must not require the dep
    except Exception as exc:  # pragma: no cover - host without pytesseract
        raise OcrUnavailableError("pytesseract not installed") from exc

    _ensure_tessdata_env()

    def _run(lang: str) -> str:
        return str(pytesseract.image_to_string(img, lang=lang) or "").strip()

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.width * img.height > _MAX_OCR_IMAGE_PIXELS:
                raise OcrUnavailableError("image too large for OCR")
            try:
                return _run(langs)
            except Exception:
                # A missing language pack raises here; retry with plain eng.
                if langs == _FALLBACK_LANGS or langs == "":
                    raise
                return _run(_FALLBACK_LANGS)
    except OcrUnavailableError:
        raise
    except Exception as exc:  # tesseract missing / broken / unreadable image
        raise OcrUnavailableError(
            f"ocr failed: {type(exc).__name__}"
        ) from exc


class OcrEngine:
    """OCR engine with injectable extractor (tests swap in a fake)."""

    def __init__(
        self,
        *,
        extractor: Callable[..., str] = extract_text_with_pytesseract,
        langs: str = _DEFAULT_LANGS,
    ) -> None:
        self._extractor = extractor
        self._langs = langs

    def extract_text(self, image_bytes: bytes) -> str:
        """Extract visible text from an image; raises OcrUnavailableError."""
        return self._extractor(image_bytes, langs=self._langs)


__all__ = [
    "OcrEngine",
    "OcrUnavailableError",
    "detect_image_mime",
    "extract_text_with_pytesseract",
]
