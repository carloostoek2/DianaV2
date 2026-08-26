"""ImageVisionService — orchestrates the image privacy filter + captioning.

Application layer (orchestration only; no business text is generated here):

1. Local OCR (never leaves the box) extracts the image text.
2. Sensitivity rules decide: sensitive ⇒ the image NEVER goes to Google and
   the owner reviews it manually. Fail-closed: if OCR cannot run or the image
   is unreadable, the image is treated as sensitive.
3. Non-sensitive images go to the cognitive ImageDescriber (Gemini) for a
   short caption; a caption failure is fail-open (plain media tag).

The image bytes are never persisted — only text (caption or the "sensitive"
mark) enters the pipeline as part of the turn text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from diana.cognitive.image_vision import ImageDescriber
from diana.infrastructure.vision.ocr import OcrEngine, OcrUnavailableError

# --- Sensitivity rules (owner-approved, 2026-08-26) --------------------------
# Categories: credit/debit cards, invoices/receipts, identity documents,
# credentials/access. Spanish (neutral) + English keywords because OCR may read
# either. Conservative by design: a match routes the image to manual owner
# review — never to Google.

# 16-digit card in 4-groups: 1234 5678 9012 3456 (also 1234-5678-...).
_CARD_GROUPED_16 = re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)")
# 15-digit Amex style: 4-6-5 groups.
_CARD_AMEX = re.compile(r"(?<!\d)\d{4}[\s-]?\d{6}[\s-]?\d{5}(?!\d)")
# 13–19 contiguous digits (validated with Luhn to avoid false positives).
_CARD_CONTIGUOUS = re.compile(r"(?<!\d)\d{13,19}(?!\d)")

_KEYWORD_PATTERNS: dict[str, tuple[str, ...]] = {
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
    for name, keys in _KEYWORD_PATTERNS.items()
}


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


def classify_sensitive(text: str) -> tuple[bool, str | None]:
    """Return (is_sensitive, reason) for extracted text + caption.

    Pure function (no I/O) so it is trivially testable. Matches are
    conservative: any hit routes to manual review.
    """
    haystack = text or ""
    # Cards: grouped patterns are strong signals; contiguous 13-19 digits must
    # pass Luhn to avoid flagging dates/order numbers as cards.
    if _CARD_GROUPED_16.search(haystack):
        return True, "tarjeta"
    if _CARD_AMEX.search(haystack):
        return True, "tarjeta"
    for match in _CARD_CONTIGUOUS.finditer(haystack):
        digits = "".join(ch for ch in match.group(0) if ch.isdigit())
        if luhn_valid(digits):
            return True, "tarjeta"
    for name, pattern in _KEYWORD_RE.items():
        if pattern.search(haystack):
            return True, name
    return False, None


@dataclass(frozen=True, slots=True)
class ImageVisionResult:
    """Outcome of analyzing an inbound photo.

    ``enabled=False`` ⇒ feature off ⇒ the caller keeps today's plain media tag.
    ``sensitive=True`` ⇒ never sent to Google; owner reviews manually.
    ``description`` is only set for non-sensitive images Gemini could caption.
    """

    enabled: bool
    sensitive: bool | None = None
    reason: str | None = None
    description: str | None = None


class ImageVisionService:
    """Orchestrates OCR filter + captioning for one inbound image."""

    def __init__(
        self,
        ocr: OcrEngine,
        describer: ImageDescriber | None,
        *,
        enabled: bool,
        classify: Callable[[str], tuple[bool, str | None]] = classify_sensitive,
    ) -> None:
        self._ocr = ocr
        self._describer = describer
        self._enabled = bool(enabled) and describer is not None
        self._classify = classify

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def analyze(
        self,
        image_bytes: bytes,
        *,
        mime_type: str,
        caption: str = "",
    ) -> ImageVisionResult:
        """Analyze one image. Fail-closed on OCR; fail-open on caption."""
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
        # 2) Sensitivity rules over OCR text + user caption.
        combined = f"{ocr_text}\n{caption}".strip()
        sensitive, reason = self._classify(combined)
        if sensitive:
            return ImageVisionResult(
                enabled=True, sensitive=True, reason=reason
            )
        # 3) Non-sensitive ⇒ caption via Gemini (fail-open on errors).
        description = await self._describer.describe(
            image_bytes, mime_type=mime_type
        )
        return ImageVisionResult(
            enabled=True,
            sensitive=False,
            reason=None,
            description=description,
        )


__all__ = [
    "ImageVisionResult",
    "ImageVisionService",
    "classify_sensitive",
    "luhn_valid",
]
