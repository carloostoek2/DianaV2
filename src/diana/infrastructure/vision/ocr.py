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
from dataclasses import dataclass
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

_FORMAT_BY_MIME: dict[str, str] = {v: k for k, v in _MIME_BY_FORMAT.items()}


def pil_format_for_mime(mime_type: str | None) -> str | None:
    """PIL format name for a MIME type (e.g. image/png → PNG), or None."""
    if not mime_type:
        return None
    return _FORMAT_BY_MIME.get(str(mime_type).strip().lower())

# Default languages: Spanish first (better accents/invoices), English fallback.
# ``eng`` alone always works — digits are universal and latin text is readable.
_DEFAULT_LANGS = "spa+eng"
_FALLBACK_LANGS = "eng"

_MAX_OCR_IMAGE_PIXELS = 4000 * 4000  # guard against decompression bombs

# --- "No verificable" evidence (owner decision, 2026-10-24) -----------------
# When OCR returns no text, the image is only clean when it really has no
# text. Three local, cheap signals say "there is something to read but the
# reader could not read it" (or "the image is unusable"):
#   * word boxes from image_to_data with non-empty text (unreadable marks),
#   * very low sharpness (blur): variance of the Laplacian,
#   * very low contrast: standard deviation of the grayscale image.
# Thresholds are deliberately conservative: a normal photo (landscape, person)
# has edges/texture and passes; a blurred document or a flat scan does not.
_MIN_SHARPNESS = 10.0
_MIN_CONTRAST = 8.0
_MIN_EVIDENCE_CONFIDENCE = 20
_EVIDENCE_MAX_DIM = 512  # measure on a bounded copy (speed, consistent scale)

# Repo-local language data (runtime/tessdata, gitignored) — installed when the
# host filesystem is read-only so the container keeps spa+eng working.
_REPO_TESSDATA = Path(__file__).resolve().parents[3] / "runtime" / "tessdata"
_HOME_TESSDATA = Path.home() / ".tessdata"


class OcrUnavailableError(RuntimeError):
    """OCR cannot run on this host (tesseract missing/broken) or on this image.

    Callers must treat this as "cannot verify" ⇒ sensitive (fail-closed): an
    image we cannot read locally must never be sent to an external provider.
    """


@dataclass(frozen=True, slots=True)
class OcrBox:
    """Bounding box of one OCR word, in pixels of the original image."""

    text: str
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True, slots=True)
class OcrLine:
    """One OCR text line: words plus the union box of the whole line.

    ``text`` is the line's words joined with spaces — used for per-line
    privacy classification. The union box is what redaction paints over.
    """

    text: str
    left: int
    top: int
    width: int
    height: int
    words: tuple[OcrBox, ...] = ()

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True, slots=True)
class ImageEvidence:
    """Local quality evidence for an image whose OCR returned no text.

    ``text_marks`` counts word boxes with text that the text extractor could
    not assemble into a readable string. ``sharpness`` (Laplacian variance)
    and ``contrast`` (grayscale standard deviation) tell a genuinely empty
    image apart from a blurred / washed-out one.
    """

    text_marks: int = 0
    sharpness: float = 0.0
    contrast: float = 0.0
    width: int = 0
    height: int = 0

    @property
    def has_unreadable_text(self) -> bool:
        return self.text_marks > 0

    @property
    def too_blurry(self) -> bool:
        return self.sharpness < _MIN_SHARPNESS

    @property
    def too_flat(self) -> bool:
        return self.contrast < _MIN_CONTRAST

    @property
    def cannot_verify(self) -> bool:
        """True ⇒ the image must not leave the server (fail-closed)."""
        return self.has_unreadable_text or self.too_blurry or self.too_flat


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


def extract_lines_with_pytesseract(
    image_bytes: bytes,
    *,
    langs: str = _DEFAULT_LANGS,
) -> tuple[OcrLine, ...]:
    """Run tesseract and return the text lines WITH their pixel boxes.

    Same engine and language fallback as ``extract_text_with_pytesseract``,
    but uses ``image_to_data`` so every word carries its exact box (the
    redaction layer paints over those boxes — never an estimate by length).
    Raises ``OcrUnavailableError`` when tesseract is missing or the image
    cannot be processed, exactly like the text extractor.
    """
    try:
        import pytesseract  # lazy: module import must not require the dep
    except Exception as exc:  # pragma: no cover - host without pytesseract
        raise OcrUnavailableError("pytesseract not installed") from exc

    _ensure_tessdata_env()

    def _run(lang: str) -> tuple[OcrLine, ...]:
        data = pytesseract.image_to_data(
            img, lang=lang, output_type=pytesseract.Output.DICT
        )
        return _group_lines(data)

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


def _group_lines(data: dict) -> tuple[OcrLine, ...]:
    """Group ``image_to_data`` words into ordered lines with union boxes."""
    groups: dict[tuple[int, int, int], list[OcrBox]] = {}
    order: list[tuple[int, int, int]] = []
    text = data.get("text") or []
    for i in range(len(text)):
        word = str(text[i] or "").strip()
        conf = int(data["conf"][i]) if i < len(data.get("conf") or []) else -1
        if not word or conf < 0:
            continue
        key = (
            int(data["block_num"][i]),
            int(data["par_num"][i]),
            int(data["line_num"][i]),
        )
        box = OcrBox(
            text=word,
            left=int(data["left"][i]),
            top=int(data["top"][i]),
            width=int(data["width"][i]),
            height=int(data["height"][i]),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(box)
    lines: list[OcrLine] = []
    for key in order:
        words = tuple(groups[key])
        left = min(w.left for w in words)
        top = min(w.top for w in words)
        right = max(w.right for w in words)
        bottom = max(w.bottom for w in words)
        lines.append(
            OcrLine(
                text=" ".join(w.text for w in words),
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
                words=words,
            )
        )
    return tuple(lines)


def _image_quality(gray: Image.Image) -> tuple[float, float]:
    """Return (sharpness, contrast) for a grayscale image.

    Sharpness is the variance of the Laplacian, computed with numpy shifts
    (no OpenCV): an in-focus image has strong second derivatives at its
    edges; a blurred one flattens them. Contrast is the grayscale standard
    deviation. Both are scale-normalized by shrinking to ``_EVIDENCE_MAX_DIM``
    first so the thresholds do not depend on the phone's resolution.
    """
    import numpy as np  # already present via the embedding stack

    gray.thumbnail((_EVIDENCE_MAX_DIM, _EVIDENCE_MAX_DIM), Image.Resampling.LANCZOS)
    array = np.asarray(gray, dtype=np.float32)
    if array.size == 0:
        return 0.0, 0.0
    contrast = float(array.std())
    if min(array.shape) < 3:
        return 0.0, contrast
    laplacian = (
        -4.0 * array
        + np.roll(array, 1, axis=0)
        + np.roll(array, -1, axis=0)
        + np.roll(array, 1, axis=1)
        + np.roll(array, -1, axis=1)
    )[1:-1, 1:-1]
    return float(laplacian.var()), contrast


def _count_text_marks(img: Image.Image, pytesseract: object, langs: str) -> int:
    """Words that image_to_data saw although image_to_string returned nothing."""

    def _run(lang: str) -> dict:
        return pytesseract.image_to_data(  # type: ignore[attr-defined]
            img, lang=lang, output_type=pytesseract.Output.DICT  # type: ignore[attr-defined]
        )

    try:
        data = _run(langs)
    except Exception:
        # A missing language pack raises here; retry with plain eng.
        if langs == _FALLBACK_LANGS or langs == "":
            raise
        data = _run(_FALLBACK_LANGS)
    texts = data.get("text") or []
    confidences = data.get("conf") or []
    marks = 0
    for index in range(len(texts)):
        if not str(texts[index] or "").strip():
            continue
        try:
            confidence = int(confidences[index])
        except (IndexError, TypeError, ValueError):
            confidence = -1
        if confidence >= _MIN_EVIDENCE_CONFIDENCE:
            marks += 1
    return marks


def probe_image_evidence(image_bytes: bytes) -> ImageEvidence:
    """Measure whether an image has text/quality that OCR failed to read.

    Raises ``OcrUnavailableError`` when the payload cannot be decoded or
    tesseract is unavailable — callers treat that as "cannot verify" too.
    """
    try:
        import pytesseract  # lazy: module import must not require the dep
    except Exception as exc:  # pragma: no cover - host without pytesseract
        raise OcrUnavailableError("pytesseract not installed") from exc

    _ensure_tessdata_env()
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.width * img.height > _MAX_OCR_IMAGE_PIXELS:
                raise OcrUnavailableError("image too large for OCR")
            width, height = img.width, img.height
            sharpness, contrast = _image_quality(img.convert("L"))
            marks = _count_text_marks(img, pytesseract, _DEFAULT_LANGS)
    except OcrUnavailableError:
        raise
    except Exception as exc:  # unreadable image / broken tesseract
        raise OcrUnavailableError(
            f"evidence probe failed: {type(exc).__name__}"
        ) from exc
    return ImageEvidence(
        text_marks=marks,
        sharpness=sharpness,
        contrast=contrast,
        width=width,
        height=height,
    )


class OcrEngine:
    """OCR engine with injectable extractor (tests swap in a fake)."""

    def __init__(
        self,
        *,
        extractor: Callable[..., str] = extract_text_with_pytesseract,
        lines_extractor: Callable[..., tuple[OcrLine, ...]] = extract_lines_with_pytesseract,
        evidence_probe: Callable[..., ImageEvidence] = probe_image_evidence,
        langs: str = _DEFAULT_LANGS,
    ) -> None:
        self._extractor = extractor
        self._lines_extractor = lines_extractor
        self._evidence_probe = evidence_probe
        self._langs = langs

    def extract_text(self, image_bytes: bytes) -> str:
        """Extract visible text from an image; raises OcrUnavailableError."""
        return self._extractor(image_bytes, langs=self._langs)

    def extract_lines(self, image_bytes: bytes) -> tuple[OcrLine, ...]:
        """Extract text lines with pixel boxes; raises OcrUnavailableError."""
        return self._lines_extractor(image_bytes, langs=self._langs)

    def probe_image(self, image_bytes: bytes) -> ImageEvidence:
        """Quality/unreadable-text evidence for an image; raises OcrUnavailableError."""
        return self._evidence_probe(image_bytes)


__all__ = [
    "ImageEvidence",
    "OcrBox",
    "OcrEngine",
    "OcrLine",
    "OcrUnavailableError",
    "detect_image_mime",
    "extract_lines_with_pytesseract",
    "extract_text_with_pytesseract",
    "pil_format_for_mime",
    "probe_image_evidence",
]
