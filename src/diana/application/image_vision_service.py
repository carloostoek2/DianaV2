"""ImageVisionService — orchestrates the image privacy filter + captioning.

Application layer (orchestration only; no business text is generated here):

1. Local OCR (never leaves the box) extracts the image text.
2. Sensitivity rules classify that text. The caption does NOT participate in
   the image decision (owner decision): it is text and rides with the
   description into the language-model pipeline, where the existing
   text-safety controls handle it like any VIP message.
   - Identity document  ⇒ sensitive (owner reviews; image never leaves,
     not even masked). Identity ALWAYS wins over a card in the same image.
   - Strong data (card / account / credential) ⇒ LOCAL REDACTION: the OCR
     line boxes are painted black; the masked image is OCR'd again and only
     if no strong data is still readable does the MASKED image go to Gemini.
   - Receipt/invoice keywords alone ⇒ nothing to hide, travels as-is (the
     amount stays visible — it is the payment proof)
   - Clean ⇒ travels as-is
3. Text that is empty or only a tiny fragment is not automatically "clean":
   if the local evidence shows unreadable text marks, or the image is blurred /
   flat (no contrast), the image is unverifiable ⇒ sensitive. A normal photo
   without text (landscape, person) is sharp and contrasty, so it still gets
   described.
4. The image that travels (masked or clean) is downscaled to a max 1280px
   edge (huge base64 payloads were timing out Gemini) and goes to the
   cognitive ImageDescriber (Gemini) for a short caption; a caption failure
   is fail-open (plain media tag).

Fail-closed: OCR unavailable/unreadable, identity documents, unavailable
boxes, a failed post-redaction verification, or an image whose text/quality
cannot be verified ⇒ sensitive (manual review). The image bytes (and the
masked copy) are never persisted — only text enters the pipeline as part of
the turn text.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable

from diana.cognitive.image_vision import ImageDescriber
from diana.infrastructure.vision.ocr import OcrEngine, OcrUnavailableError
from diana.infrastructure.vision.redact import mask_lines
from diana.infrastructure.vision.resize import downscale_image
from diana.llm.pii_masker import contains_valid_card, luhn_valid

# --- Sensitivity rules (owner-approved, 2026-08-26) --------------------------
# Categories: credit/debit cards, invoices/receipts, identity documents,
# credentials/access, bank accounts. Spanish (neutral) + English keywords
# because OCR may read either.
#
# Policy (owner decision, 2026-09):
# - identity  ⇒ manual review, image NEVER leaves (even masked)
# - strong (cards / credentials / accounts) ⇒ local redaction, masked image travels
# - receipt/invoice keywords alone ⇒ travels as-is (amount stays visible)

# Card detection lives in ONE place: the text masker (``pii_masker``). It
# covers dots, hard spaces (U+00A0), tabs, newlines and hyphens, validates
# Luhn on a group boundary and retries the prefix of a glued card+CVV. Image
# and video vision reuse it, so a 6-10, 2-14, 4-4-4-4-3 or dotted Amex shape
# is classified exactly like the same number in a chat message (H2).

_KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "factura": (
        "factura", "invoice", "recibo", "receipt", "comprobante", "voucher",
        "ticket", "orden de compra", "purchase order", "importe", "subtotal",
        "iva", "tax", "total a pagar", "total payable", "rfc", "cuit", "cuil",
        "número de factura", "numero de factura", "no. de factura",
        "transferencia", "transfer", "pago", "payment", "precio", "price",
    ),
    "identidad": (
        "dni", "pasaporte", "passport", "licencia de conducir",
        "driver license", "driver's license", "cédula", "cedula",
        "identificación", "identificacion", "documento nacional",
        "tarjeta de identidad", "id card", "matrícula", "matricula",
        "documento de identidad",
    ),
    "clave": (
        "contraseña", "contrasena", "password", "clave", "pin", "cvv", "ccv",
        "usuario", "username", "login", "token", "otp", "código de verificación",
        "codigo de verificacion", "código de seguridad", "codigo de seguridad",
        "código secreto", "codigo secreto", "2fa", "two factor",
    ),
    "cuenta": (
        "cuenta bancaria", "bank account", "iban", "clabe", "swift",
        "número de cuenta", "numero de cuenta", "número de tarjeta",
        "numero de tarjeta", "card number", "número de seguridad",
        "numero de seguridad",
    ),
}

# Compile keyword matchers once: whole word, case-insensitive.
_KEYWORD_RE: dict[str, re.Pattern[str]] = {
    name: re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keys) + r")(?!\w)",
        re.IGNORECASE,
    )
    for name, keys in _KEYWORD_GROUPS.items()
}

# Which groups are "strong data" (redactable — never leave the box readable).
_STRONG_GROUPS = frozenset({"clave", "cuenta"})

_IDENTITY_RE = _KEYWORD_RE["identidad"]

# --- Process-wide activity counters (published by /health) -------------------
# They answer "is vision armed but doing nothing / failing?" without reading
# logs. In-memory on purpose: they describe this process since boot.
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY: dict[str, dict[str, int]] = {
    "image": {"analyzed": 0, "sensitive": 0, "described": 0, "failed": 0},
    "video": {"analyzed": 0, "sensitive": 0, "described": 0, "failed": 0},
}


def record_vision_activity(kind: str, event: str) -> None:
    """Count one vision event (``image``/``video`` × analyzed/sensitive/...)."""
    counters = _ACTIVITY.get(kind)
    if counters is None or event not in counters:
        return
    with _ACTIVITY_LOCK:
        counters[event] += 1


def vision_activity_snapshot() -> dict[str, dict[str, int]]:
    """Immutable copy of the activity counters for ``/health``."""
    with _ACTIVITY_LOCK:
        return {kind: dict(values) for kind, values in _ACTIVITY.items()}


@dataclass(frozen=True, slots=True)
class SensitiveScan:
    """Class outcome for one text (whole image, a line, or the re-check).

    ``has_identity`` ⇒ manual review, nothing travels.
    ``strong``       ⇒ card/account/credential data present ⇒ redact & verify.
    ``receipt``      ⇒ invoice/receipt keywords only ⇒ travels (amount visible).
    ``reason``       ⇒ first-match category for reporting (tarjeta, factura,
                       identidad, clave, cuenta), None when clean.
    """

    has_identity: bool = False
    strong: bool = False
    receipt: bool = False
    reason: str | None = None


def _has_luhn_card(haystack: str) -> bool:
    """True when the text carries a Luhn-valid card in any accepted format.

    Delegates to the text-masker detector: dots, hyphens, hard spaces, tabs
    and newlines are separators, Luhn is applied to a group-aligned prefix
    (so a card + expiry/CVV still masks the card), and a glued card+CVV is
    also recognised. A non-card 16-digit run (order id) still travels.
    """
    return contains_valid_card(haystack)


def scan_sensitive(text: str) -> SensitiveScan:
    """Classify one text into the privacy policy buckets (pure, no I/O).

    Conservative by design, with one hard ordering rule: an identity document
    wins over everything else, including a card number on the same text. The
    image of a passport/DNI must never leave the server, not even masked; if
    the card were classified first, only that line would be redacted and the
    document would travel readable.
    """
    haystack = text or ""
    # 1) Identity first — it beats cards, receipts and credentials.
    if _IDENTITY_RE.search(haystack):
        return SensitiveScan(has_identity=True, reason="identidad")
    # 2) Cards. Every accepted shape goes through Luhn on a group-aligned
    #    prefix (the same rule the text masker uses).
    if _has_luhn_card(haystack):
        return SensitiveScan(strong=True, reason="tarjeta")
    # 3) Keyword groups (credentials / accounts / receipts).
    receipt = False
    strong = False
    reason: str | None = None
    for name, pattern in _KEYWORD_RE.items():
        if not pattern.search(haystack):
            continue
        if name in _STRONG_GROUPS:
            strong = True
        elif name == "factura":
            receipt = True
        if reason is None:
            reason = name
    return SensitiveScan(
        has_identity=False, strong=strong, receipt=receipt, reason=reason
    )


def classify_sensitive(text: str) -> tuple[bool, str | None]:
    """Backward-compatible wrapper: (is_sensitive, reason) for any text.

    Kept for callers/tests that only need the boolean verdict; the service
    itself uses :func:`scan_sensitive` for the full policy.
    """
    scan = scan_sensitive(text)
    return (scan.has_identity or scan.strong or scan.receipt, scan.reason)


# --- "Cannot verify" evidence on an image whose OCR text is missing/scarce ---
# Empty text is not proof of an empty image: a blurred document, a low-contrast
# scan or a bad read also return little or no text. Below this many non-space
# characters the local probe decides (sharpness/contrast), because the read is
# too short to trust on its own (M5).
_MIN_VERIFIABLE_TEXT_CHARS = 12


def text_is_scarce(text: str) -> bool:
    """True when the OCR text is too short to trust as a complete read.

    The observable form of a low-confidence read at this layer is a tiny text
    fragment: the extractor does not expose confidence, so the caller asks the
    local probe whether the image is blurred/flat before deciding it is clean.
    """
    return len("".join(ch for ch in text if not ch.isspace())) < (
        _MIN_VERIFIABLE_TEXT_CHARS
    )


def evidence_is_unverifiable(evidence: object | None, *, text_seen: bool) -> bool:
    """Decide from local evidence whether the image must stay on the server.

    When NO text was read, any signal counts: unreadable marks, blur or a flat
    image. When some text WAS read, only blur/flatness count — those are what
    hide ADDITIONAL text the reader never saw; ``text_marks`` is expected on a
    readable image and must not block it.
    """
    if evidence is None:
        return False
    if text_seen:
        return bool(
            getattr(evidence, "too_blurry", False)
            or getattr(evidence, "too_flat", False)
        )
    return bool(getattr(evidence, "cannot_verify", False))


@dataclass(frozen=True, slots=True)
class ImageVisionResult:
    """Outcome of analyzing an inbound photo.

    ``enabled=False`` ⇒ feature off ⇒ the caller keeps today's plain media tag.
    ``sensitive=True`` ⇒ never sent to Google; owner reviews manually.
    ``description`` is only set for images Gemini could caption (masked or clean).
    ``masked=True`` ⇒ the image that traveled was locally redacted.
    """

    enabled: bool
    sensitive: bool | None = None
    reason: str | None = None
    description: str | None = None
    masked: bool = False


class ImageVisionService:
    """Orchestrates OCR filter + local redaction + captioning for one image."""

    def __init__(
        self,
        ocr: OcrEngine,
        describer: ImageDescriber | None,
        *,
        enabled: bool,
        scan: Callable[[str], SensitiveScan] = scan_sensitive,
    ) -> None:
        self._ocr = ocr
        self._describer = describer
        self._enabled = bool(enabled) and describer is not None
        self._scan = scan

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def analyze(self, image_bytes: bytes, *, mime_type: str) -> ImageVisionResult:
        """Analyze one image. Fail-closed on privacy; fail-open on caption."""
        if not self._enabled:
            return ImageVisionResult(enabled=False)
        record_vision_activity("image", "analyzed")
        # 1) Local OCR — the image never leaves the box at this stage.
        try:
            ocr_text = self._ocr.extract_text(image_bytes)
        except OcrUnavailableError:
            # Cannot verify ⇒ treat as sensitive (privacy wins).
            return self._sensitive("no_legible")
        # 1b) No text — or only a tiny fragment: is it a photo without text
        #     (clean) or an image the reader could not read (blurred / flat /
        #     unreadable marks)? Only the second case is sensitive.
        if text_is_scarce(ocr_text):
            try:
                evidence = self._probe(image_bytes)
            except OcrUnavailableError:
                return self._sensitive("no_legible")
            if evidence_is_unverifiable(
                evidence, text_seen=bool(ocr_text.strip())
            ):
                return self._sensitive("no_verificable")
        # 2) Policy over the OCR text (the caption is text, not pixels: it
        #    rides with the description into the language-model pipeline).
        scan = self._scan(ocr_text)
        if scan.has_identity:
            # Identity documents never leave the server, not even masked.
            return self._sensitive("identidad")
        if scan.strong:
            # 3) Redact locally, then verify before anything travels.
            masked = self._mask_sensitive(image_bytes, mime_type=mime_type)
            if masked is None:
                return self._sensitive("mask_unavailable")
            try:
                verify_text = self._ocr.extract_text(masked)
            except OcrUnavailableError:
                return self._sensitive("mask_verification_failed")
            if self._scan(verify_text).strong:
                # The mask did not fully hide the data ⇒ fail-closed.
                return self._sensitive("mask_verification_failed")
            send_bytes, send_mime = self._prepare_for_gemini(masked, mime_type)
            description = await self._describer.describe(
                send_bytes, mime_type=send_mime
            )
            if description is not None:
                record_vision_activity("image", "described")
            return ImageVisionResult(
                enabled=True,
                sensitive=False,
                reason=None,
                description=description,
                masked=True,
            )
        # 4) Clean (or receipt keywords alone — nothing to hide; the amount
        #    stays visible) ⇒ travels as today.
        send_bytes, send_mime = self._prepare_for_gemini(image_bytes, mime_type)
        description = await self._describer.describe(
            send_bytes, mime_type=send_mime
        )
        if description is not None:
            record_vision_activity("image", "described")
        return ImageVisionResult(
            enabled=True,
            sensitive=False,
            reason=None,
            description=description,
        )

    def _sensitive(self, reason: str) -> ImageVisionResult:
        record_vision_activity("image", "sensitive")
        return ImageVisionResult(enabled=True, sensitive=True, reason=reason)

    def _probe(self, image_bytes: bytes) -> object | None:
        """Local evidence probe; ``None`` when the injected OCR has none.

        The real ``OcrEngine`` always provides it. Test doubles without the
        method keep the previous behavior (empty text ⇒ clean) so the pure
        orchestration tests do not need a real tesseract.
        """
        probe = getattr(self._ocr, "probe_image", None)
        if probe is None:
            return None
        return probe(image_bytes)

    def _prepare_for_gemini(
        self, image_bytes: bytes, mime_type: str
    ) -> tuple[bytes, str]:
        """Downscale before the external caption call.

        Full-res phone photos produced huge base64 payloads that exceeded
        Gemini's read timeout (fail-open placeholder). Returns (bytes,
        mime_type); the original pair when the image is already small or the
        resize fails.
        """
        resized = downscale_image(image_bytes)
        if resized is None:
            return image_bytes, mime_type
        return resized, "image/jpeg"

    def _mask_sensitive(self, image_bytes: bytes, *, mime_type: str) -> bytes | None:
        """Return masked bytes, or None when masking cannot guarantee hiding."""
        try:
            lines = self._ocr.extract_lines(image_bytes)
        except OcrUnavailableError:
            return None
        to_mask = tuple(ln for ln in lines if self._scan(ln.text).strong)
        if not to_mask:
            # Strong data was seen in the whole text but not on any single
            # line (data split across lines / OCR mismatch) ⇒ fail-closed.
            return None
        return mask_lines(image_bytes, to_mask, mime_type=mime_type)


__all__ = [
    "ImageVisionResult",
    "ImageVisionService",
    "SensitiveScan",
    "classify_sensitive",
    "evidence_is_unverifiable",
    "luhn_valid",
    "record_vision_activity",
    "scan_sensitive",
    "text_is_scarce",
    "vision_activity_snapshot",
]
