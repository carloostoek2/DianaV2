"""ImageVisionService — OCR privacy filter + local redaction orchestration (unit)."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from diana.application.image_vision_service import (
    ImageVisionService,
    SensitiveScan,
    classify_sensitive,
    luhn_valid,
    scan_sensitive,
)
from diana.cognitive.image_vision import ImageDescriber
from diana.infrastructure.vision.ocr import OcrLine, OcrUnavailableError


def _png_bytes(width: int = 64, height: int = 32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def _fake_ocr(
    text: str | type[Exception],
    *,
    lines: tuple[OcrLine, ...] = (),
    lines_error: type[Exception] | None = None,
    verify_text: str = "",
) -> SimpleNamespace:
    """OcrEngine-compatible fake: extract_text + extract_lines with counters.

    ``text`` is returned on the first extract_text call; ``verify_text`` on
    later calls (the post-redaction re-check). ``lines`` feed extract_lines.
    """
    calls = {"text": 0, "lines": 0}

    def extract_text(_b):
        calls["text"] += 1
        if isinstance(text, type):
            raise text()
        return text if calls["text"] == 1 else verify_text

    def extract_lines(_b):
        calls["lines"] += 1
        if lines_error is not None:
            raise lines_error()
        return lines

    return SimpleNamespace(
        extract_text=extract_text, extract_lines=extract_lines
    )


class _SpyVision:
    def __init__(self, text: str | None = None, error: bool = False) -> None:
        self._text = text
        self._error = error
        self.seen_bytes: bytes | None = None
        self.seen_mime: str | None = None
        self.calls = 0

    async def describe_image(self, image_bytes, *, mime_type, prompt) -> str:
        self.calls += 1
        self.seen_bytes = image_bytes
        self.seen_mime = mime_type
        if self._error:
            raise RuntimeError("gemini down")
        return self._text


def _service(
    *,
    ocr_text: str | type[Exception] = "",
    vision_text: str = "una foto del plato",
    enabled: bool = True,
    vision_error: bool = False,
    lines: tuple[OcrLine, ...] = (),
    verify_text: str = "",
    lines_error: type[Exception] | None = None,
) -> tuple[ImageVisionService, _SpyVision]:
    ocr = _fake_ocr(
        ocr_text, lines=lines, lines_error=lines_error, verify_text=verify_text
    )
    vision = _SpyVision(vision_text, error=vision_error)
    describer = ImageDescriber(vision=vision)
    svc = ImageVisionService(ocr=ocr, describer=describer, enabled=enabled)
    return svc, vision


# --- classify_sensitive / scan_sensitive: pure rules ------------------------

def test_card_grouped_16_digits() -> None:
    assert classify_sensitive("mi tarjeta es 1234 5678 9012 3456") == (True, "tarjeta")
    assert classify_sensitive("1234-5678-9012-3456") == (True, "tarjeta")


def test_card_amex_style() -> None:
    assert classify_sensitive("3782 822463 10005") == (True, "tarjeta")


def test_card_luhn_contiguous() -> None:
    # 4532015112830366 is a valid Luhn card number.
    assert classify_sensitive("numero: 4532015112830366") == (True, "tarjeta")


def test_long_digit_run_without_luhn_is_not_card() -> None:
    assert classify_sensitive("orden 20240512123000123") == (False, None)


def test_dates_are_not_cards() -> None:
    assert classify_sensitive("2024 05 12 / 2025 06 30") == (False, None)


def test_invoice_keywords() -> None:
    assert classify_sensitive("FACTURA No 0042 Total: 1250.00") == (True, "factura")
    assert classify_sensitive("Invoice #9 total $42") == (True, "factura")


def test_identity_documents() -> None:
    assert classify_sensitive("mi DNI es 30445566") == (True, "identidad")
    assert classify_sensitive("pasaporte argentino") == (True, "identidad")
    assert classify_sensitive("licencia de conducir") == (True, "identidad")


def test_credentials() -> None:
    assert classify_sensitive("contraseña: abc123") == (True, "clave")
    assert classify_sensitive("cvv 123") == (True, "clave")
    assert classify_sensitive("código de verificación 8812") == (True, "clave")


def test_bank_account_terms() -> None:
    assert classify_sensitive("CLABE 012345678901234567") == (True, "cuenta")
    assert classify_sensitive("cuenta bancaria 123") == (True, "cuenta")


def test_clean_text_is_not_sensitive() -> None:
    assert classify_sensitive("hola mira la foto de mi perro en el parque") == (False, None)
    assert classify_sensitive("") == (False, None)


def test_luhn_valid_math() -> None:
    assert luhn_valid("4532015112830366") is True
    assert luhn_valid("1234567890123456") is False
    assert luhn_valid("abc") is False


def test_scan_policy_buckets() -> None:
    identity = scan_sensitive("mi DNI es 30445566")
    assert identity.has_identity is True and identity.strong is False
    strong = scan_sensitive("1234 5678 9012 3456")
    assert strong.strong is True and strong.has_identity is False
    receipt = scan_sensitive("FACTURA Total 99.90")
    assert receipt.receipt is True and receipt.strong is False
    clean = scan_sensitive("un perro en el parque")
    assert clean == SensitiveScan()


def test_scan_identity_wins_over_receipt() -> None:
    scan = scan_sensitive("FACTURA\nmi DNI")
    assert scan.has_identity is True


# --- ImageVisionService orchestration ---------------------------------------

@pytest.mark.asyncio
async def test_disabled_feature_returns_plain_result() -> None:
    svc, _ = _service(enabled=False)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.enabled is False
    assert result.sensitive is None
    assert result.description is None


@pytest.mark.asyncio
async def test_disabled_without_describer() -> None:
    ocr = _fake_ocr("")
    svc = ImageVisionService(ocr=ocr, describer=None, enabled=True)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.enabled is False  # no captioner ⇒ feature inert


@pytest.mark.asyncio
async def test_ocr_unavailable_is_fail_closed_sensitive() -> None:
    svc, vision = _service(ocr_text=OcrUnavailableError)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "no_legible"
    assert result.description is None
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_identity_document_never_leaves_not_even_masked() -> None:
    svc, vision = _service(ocr_text="mi DNI es 30445566")
    result = await svc.analyze(_png_bytes(), mime_type="image/png")
    assert result.sensitive is True
    assert result.reason == "identidad"
    assert result.description is None
    assert result.masked is False
    assert vision.calls == 0  # nothing traveled


@pytest.mark.asyncio
async def test_receipt_keywords_travel_unmasked_amount_visible() -> None:
    svc, vision = _service(ocr_text="FACTURA No 0042 Total: 1250.00")
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is False
    assert result.masked is False
    assert result.description == "una foto del plato"
    assert vision.seen_bytes == b"img"  # the original image traveled as-is


@pytest.mark.asyncio
async def test_card_gets_redacted_and_travels_masked() -> None:
    line = OcrLine(
        text="1234 5678 9012 3456", left=10, top=10, width=200, height=30
    )
    svc, vision = _service(
        ocr_text="1234 5678 9012 3456", lines=(line,), verify_text=""
    )
    original = _png_bytes()
    result = await svc.analyze(original, mime_type="image/png")
    assert result.sensitive is False
    assert result.masked is True
    assert result.description == "una foto del plato"
    assert vision.calls == 1
    assert vision.seen_bytes != original  # the masked copy traveled, not the original


@pytest.mark.asyncio
async def test_redaction_verification_failure_is_fail_closed() -> None:
    # After masking, the re-check still reads a card number ⇒ manual review.
    line = OcrLine(
        text="1234 5678 9012 3456", left=10, top=10, width=200, height=30
    )
    svc, vision = _service(
        ocr_text="1234 5678 9012 3456",
        lines=(line,),
        verify_text="1234 5678 9012 3456",
    )
    result = await svc.analyze(_png_bytes(), mime_type="image/png")
    assert result.sensitive is True
    assert result.reason == "mask_verification_failed"
    assert vision.calls == 0  # nothing traveled


@pytest.mark.asyncio
async def test_redaction_unavailable_boxes_is_fail_closed() -> None:
    # Strong data found but no OCR lines to paint ⇒ never send.
    svc, vision = _service(ocr_text="1234 5678 9012 3456", lines=())
    result = await svc.analyze(_png_bytes(), mime_type="image/png")
    assert result.sensitive is True
    assert result.reason == "mask_unavailable"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_redaction_lines_error_is_fail_closed() -> None:
    svc, vision = _service(
        ocr_text="1234 5678 9012 3456", lines_error=OcrUnavailableError
    )
    result = await svc.analyze(_png_bytes(), mime_type="image/png")
    assert result.sensitive is True
    assert result.reason == "mask_unavailable"


@pytest.mark.asyncio
async def test_receipt_with_account_number_masks_only_strong_line() -> None:
    lines = (
        OcrLine(text="FACTURA", left=10, top=10, width=120, height=24),
        OcrLine(
            text="CLABE 012345678901234567",
            left=10,
            top=40,
            width=260,
            height=24,
        ),
        OcrLine(text="TOTAL 1250.00", left=10, top=70, width=160, height=24),
    )
    svc, vision = _service(
        ocr_text="FACTURA\nCLABE 012345678901234567\nTOTAL 1250.00",
        lines=lines,
    )
    result = await svc.analyze(_png_bytes(320, 120), mime_type="image/png")
    assert result.sensitive is False
    assert result.masked is True  # the CLABE line was hidden
    assert result.description == "una foto del plato"


@pytest.mark.asyncio
async def test_clean_image_gets_caption() -> None:
    svc, vision = _service(ocr_text="", vision_text="una foto del plato")
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is False
    assert result.masked is False
    assert result.description == "una foto del plato"
    assert vision.seen_bytes == b"img"


@pytest.mark.asyncio
async def test_captioner_failure_is_fail_open() -> None:
    svc, _ = _service(ocr_text="", vision_error=True)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is False
    assert result.description is None


@pytest.mark.asyncio
async def test_redacted_image_describer_failure_is_fail_open() -> None:
    line = OcrLine(
        text="1234 5678 9012 3456", left=10, top=10, width=200, height=30
    )
    svc, _ = _service(
        ocr_text="1234 5678 9012 3456",
        lines=(line,),
        vision_error=True,
    )
    result = await svc.analyze(_png_bytes(), mime_type="image/png")
    assert result.sensitive is False
    assert result.masked is True
    assert result.description is None


def _max_edge(img: Image.Image) -> int:
    return max(img.width, img.height)


@pytest.mark.asyncio
async def test_large_clean_image_is_downscaled_before_gemini() -> None:
    svc, vision = _service(ocr_text="", vision_text="un concierto al aire libre")
    result = await svc.analyze(_png_bytes(2000, 1500), mime_type="image/png")
    assert result.sensitive is False
    assert result.description == "un concierto al aire libre"
    with Image.open(io.BytesIO(vision.seen_bytes)) as img:
        assert img.format == "JPEG"
        assert _max_edge(img) <= 1280
    assert vision.seen_mime == "image/jpeg"


@pytest.mark.asyncio
async def test_small_clean_image_travels_as_is() -> None:
    svc, vision = _service(ocr_text="", vision_text="una foto del plato")
    original = _png_bytes(64, 32)
    result = await svc.analyze(original, mime_type="image/png")
    assert result.sensitive is False
    assert vision.seen_bytes == original
    assert vision.seen_mime == "image/png"


@pytest.mark.asyncio
async def test_large_masked_image_is_downscaled_before_gemini() -> None:
    line = OcrLine(
        text="1234 5678 9012 3456", left=10, top=10, width=300, height=30
    )
    svc, vision = _service(
        ocr_text="1234 5678 9012 3456", lines=(line,), verify_text=""
    )
    result = await svc.analyze(_png_bytes(2000, 1500), mime_type="image/png")
    assert result.sensitive is False
    assert result.masked is True
    with Image.open(io.BytesIO(vision.seen_bytes)) as img:
        assert img.format == "JPEG"
        assert _max_edge(img) <= 1280
    assert vision.seen_mime == "image/jpeg"
