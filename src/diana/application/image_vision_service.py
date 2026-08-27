"""ImageVisionService — orchestrates the image privacy filter + captioning.

Application layer (orchestration only; no business text is generated here):

1. Local OCR (never leaves the box) extracts the image text.
2. Sensitivity rules classify that text. The caption does NOT participate in
   the image decision (owner decision): it is text and rides with the
   description into the language-model pipeline, where the existing
   text-safety controls handle it like any VIP message.
   - Identity document  ⇒ sensitive (owner reviews; image never leaves,
     not even masked)
   - Strong data (card / account / credential) ⇒ LOCAL REDACTION: the OCR
     line boxes are painted black; the masked image is OCR'd again and only
     if no strong data is still readable does the MASKED image go to Gemini
   - Receipt/invoice keywords alone ⇒ nothing to hide, travels as-is (the
     amount stays visible — it is the payment proof)
   - Clean ⇒ travels as-is
3. The image that travels (masked or clean) goes to the cognitive
   ImageDescriber (Gemini) for a short caption; a caption failure is
   fail-open (plain media tag).

Fail-closed: OCR unavailable/unreadable, identity documents, unavailable
boxes, or a failed post-redaction verification ⇒ sensitive (manual review).
The image bytes (and the masked copy) are never persisted — only text enters
the pipeline as part of the turn text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from diana.cognitive.image_vision import ImageDescriber
from diana.infrastructure.vision.ocr import OcrEngine, OcrUnavailableError
from diana.infrastructure.vision.redact import mask_lines

# --- Sensitivity rules (owner-approved, 2026-08-26) --------------------------
# Categories: credit/debit cards, invoices/receipts, identity documents,
# credentials/access, bank accounts. Spanish (neutral) + English keywords
# because OCR may read either.
#
# Policy (owner decision, 2026-09):
# - identity  ⇒ manual review, image NEVER leaves (even masked)
# - strong (cards / credentials / accounts) ⇒ local redaction, masked image travels
# - receipt/invoice keywords alone ⇒ travels as-is (amount stays visible)

# 16-digit card in 4-groups: 1234 5678 9012 3456 (also 1234-5678-...).
_CARD_GROUPED_16 = re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)")
# 15-digit Amex style: 4-6-5 groups.
_CARD_AMEX = re.compile(r"(?<!\d)\d{4}[\s-]?\d{6}[\s-]?\d{5}(?!\d)")
# 13–19 contiguous digits (validated with Luhn to avoid false positives).
_CARD_CONTIGUOUS = re.compile(r"(?<!\d)\d{13,19}(?!\d)")

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


def luhn_valid(digits: str) -> bool:
    """Luhn checksum for card numbers (reduces false positives on long IDs)."""
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        if not ch.isdigit():
            return False
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


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


def scan_sensitive(text: str) -> SensitiveScan:
    """Classify one text into the privacy policy buckets (pure, no I/O).

    Conservative by design: cards match on strong patterns, any keyword hit
    routes the whole image to redaction or manual review, never to Google in
    readable form.
    """
    haystack = text or ""
    # Cards: grouped patterns are strong signals; contiguous 13-19 digits must
    # pass Luhn to avoid flagging dates/order numbers as cards.
    if _CARD_GROUPED_16.search(haystack) or _CARD_AMEX.search(haystack):
        return SensitiveScan(strong=True, reason="tarjeta")
    for match in _CARD_CONTIGUOUS.finditer(haystack):
        digits = "".join(ch for ch in match.group(0) if ch.isdigit())
        if luhn_valid(digits):
            return SensitiveScan(strong=True, reason="tarjeta")
    receipt = False
    strong = False
    reason: str | None = None
    for name, pattern in _KEYWORD_RE.items():
        if pattern.search(haystack):
            if name == "identidad":
                # Identity wins over everything else: never leaves, even masked.
                return SensitiveScan(
                    has_identity=True, strong=strong, receipt=receipt, reason="identidad"
                )
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
        # 1) Local OCR — the image never leaves the box at this stage.
        try:
            ocr_text = self._ocr.extract_text(image_bytes)
        except OcrUnavailableError:
            # Cannot verify ⇒ treat as sensitive (privacy wins).
            return ImageVisionResult(
                enabled=True, sensitive=True, reason="no_legible"
            )
        # 2) Policy over the OCR text (the caption is text, not pixels: it
        #    rides with the description into the language-model pipeline).
        scan = self._scan(ocr_text)
        if scan.has_identity:
            # Identity documents never leave the server, not even masked.
            return ImageVisionResult(
                enabled=True, sensitive=True, reason="identidad"
            )
        if scan.strong:
            # 3) Redact locally, then verify before anything travels.
            masked = self._mask_sensitive(image_bytes, mime_type=mime_type)
            if masked is None:
                return ImageVisionResult(
                    enabled=True, sensitive=True, reason="mask_unavailable"
                )
            try:
                verify_text = self._ocr.extract_text(masked)
            except OcrUnavailableError:
                return ImageVisionResult(
                    enabled=True, sensitive=True, reason="mask_verification_failed"
                )
            if self._scan(verify_text).strong:
                # The mask did not fully hide the data ⇒ fail-closed.
                return ImageVisionResult(
                    enabled=True, sensitive=True, reason="mask_verification_failed"
                )
            description = await self._describer.describe(
                masked, mime_type=mime_type
            )
            return ImageVisionResult(
                enabled=True,
                sensitive=False,
                reason=None,
                description=description,
                masked=True,
            )
        # 4) Clean (or receipt keywords alone — nothing to hide; the amount
        #    stays visible) ⇒ travels as today.
        description = await self._describer.describe(
            image_bytes, mime_type=mime_type
        )
        return ImageVisionResult(
            enabled=True,
            sensitive=False,
            reason=None,
            description=description,
        )

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
    "luhn_valid",
    "scan_sensitive",
]
