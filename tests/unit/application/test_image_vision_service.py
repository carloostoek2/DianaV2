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
from diana.infrastructure.vision.ocr import (
    ImageEvidence,
    OcrEngine,
    OcrLine,
    OcrUnavailableError,
)


def _png_bytes(width: int = 64, height: int = 32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


# A normal photo-like payload for the evidence path: no text, sharp edges,
# normal contrast. The empty-text cases must NOT be treated as unverifiable.
_CLEAN_EVIDENCE = ImageEvidence(
    text_marks=0, sharpness=250.0, contrast=40.0, width=64, height=32
)


def _fake_ocr(
    text: str | type[Exception],
    *,
    lines: tuple[OcrLine, ...] = (),
    lines_error: type[Exception] | None = None,
    verify_text: str = "",
    evidence: ImageEvidence | None = None,
    evidence_error: type[Exception] | None = None,
) -> SimpleNamespace:
    """OcrEngine-compatible fake: extract_text + extract_lines + probe_image.

    ``text`` is returned on the first extract_text call; ``verify_text`` on
    later calls (the post-redaction re-check). ``lines`` feed extract_lines.
    ``evidence`` feeds the empty-text quality probe (default: clean photo).
    """
    calls = {"text": 0, "lines": 0, "probe": 0}

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

    def probe_image(_b):
        calls["probe"] += 1
        if evidence_error is not None:
            raise evidence_error()
        return evidence if evidence is not None else _CLEAN_EVIDENCE

    return SimpleNamespace(
        extract_text=extract_text,
        extract_lines=extract_lines,
        probe_image=probe_image,
        calls=calls,
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
    evidence: ImageEvidence | None = None,
    evidence_error: type[Exception] | None = None,
) -> tuple[ImageVisionService, _SpyVision]:
    ocr = _fake_ocr(
        ocr_text,
        lines=lines,
        lines_error=lines_error,
        verify_text=verify_text,
        evidence=evidence,
        evidence_error=evidence_error,
    )
    vision = _SpyVision(vision_text, error=vision_error)
    describer = ImageDescriber(vision=vision)
    svc = ImageVisionService(ocr=ocr, describer=describer, enabled=enabled)
    return svc, vision


# --- classify_sensitive / scan_sensitive: pure rules ------------------------

def test_card_grouped_16_digits() -> None:
    assert classify_sensitive("mi tarjeta es 4111 1111 1111 1111") == (True, "tarjeta")
    assert classify_sensitive("4111-1111-1111-1111") == (True, "tarjeta")


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
    strong = scan_sensitive("4111 1111 1111 1111")
    assert strong.strong is True and strong.has_identity is False
    receipt = scan_sensitive("FACTURA Total 99.90")
    assert receipt.receipt is True and receipt.strong is False
    clean = scan_sensitive("un perro en el parque")
    assert clean == SensitiveScan()


def test_scan_identity_wins_over_receipt() -> None:
    scan = scan_sensitive("FACTURA\nmi DNI")
    assert scan.has_identity is True


def test_identity_wins_over_a_16_digit_card() -> None:
    """Un documento de identidad SIEMPRE gana: no se clasifica como tarjeta."""
    scan = scan_sensitive(
        "DOCUMENTO NACIONAL DE IDENTIDAD\nDNI 30445566\n4111 1111 1111 1111"
    )
    assert scan.has_identity is True
    assert scan.reason == "identidad"
    assert scan.strong is False


def test_card_separators_cover_dots_hard_spaces_tabs_and_newlines() -> None:
    for text in (
        "4111.1111.1111.1111",
        "4111 1111 1111 1111",
        "4111\t1111\n1111 1111",
        "4111-1111-1111-1111",
    ):
        scan = scan_sensitive(text)
        assert scan.strong is True and scan.reason == "tarjeta", text


def test_sixteen_digits_must_pass_luhn() -> None:
    """Una corrida de 16 dígitos solo se enmascara si es una tarjeta válida."""
    assert scan_sensitive("1234567890123456").strong is False
    assert scan_sensitive("1234 5678 9012 3456").strong is False
    assert scan_sensitive("4111111111111111").strong is True
    assert scan_sensitive("4111 1111 1111 1111").strong is True


def test_card_formats_found_by_the_audit_are_detected() -> None:
    """H2: la detección de tarjeta es la misma del enmascarador de texto.

    Amex con puntos, 16 dígitos agrupados 6-10 o 2-14 y la forma 4-4-4-4-3
    (tarjeta + CVV) viajaban legibles porque los patrones locales de la
    visión solo aceptaban espacio y guion. Ahora comparten una sola función
    con Luhn sobre el prefijo.
    """
    for text in (
        "3782.822463.10005",
        "411111 1111111111",
        "41 11111111111111",
        "4111 1111 1111 1111 123",
    ):
        scan = scan_sensitive(text)
        assert scan.strong is True and scan.reason == "tarjeta", text


def test_non_luhn_sixteen_digits_still_travels_in_the_image_filter() -> None:
    """El criterio de Luhn sigue evitando tapar números de pedido."""
    assert scan_sensitive("PEDIDO 1234567890123456").strong is False


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
        text="4111 1111 1111 1111", left=10, top=10, width=200, height=30
    )
    svc, vision = _service(
        ocr_text="4111 1111 1111 1111", lines=(line,), verify_text=""
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
        text="4111 1111 1111 1111", left=10, top=10, width=200, height=30
    )
    svc, vision = _service(
        ocr_text="4111 1111 1111 1111",
        lines=(line,),
        verify_text="4111 1111 1111 1111",
    )
    result = await svc.analyze(_png_bytes(), mime_type="image/png")
    assert result.sensitive is True
    assert result.reason == "mask_verification_failed"
    assert vision.calls == 0  # nothing traveled


@pytest.mark.asyncio
async def test_redaction_unavailable_boxes_is_fail_closed() -> None:
    # Strong data found but no OCR lines to paint ⇒ never send.
    svc, vision = _service(ocr_text="4111 1111 1111 1111", lines=())
    result = await svc.analyze(_png_bytes(), mime_type="image/png")
    assert result.sensitive is True
    assert result.reason == "mask_unavailable"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_redaction_lines_error_is_fail_closed() -> None:
    svc, vision = _service(
        ocr_text="4111 1111 1111 1111", lines_error=OcrUnavailableError
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
async def test_empty_ocr_on_a_normal_photo_is_clean_and_described() -> None:
    """Una foto normal sin texto (paisaje, persona) sigue su curso."""
    svc, vision = _service(ocr_text="", evidence=_CLEAN_EVIDENCE)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is False
    assert result.description == "una foto del plato"
    assert vision.calls == 1


@pytest.mark.asyncio
async def test_empty_ocr_with_unreadable_text_marks_is_sensitive() -> None:
    """Hay marcas de texto que el lector no pudo leer ⇒ no se envía."""
    evidence = ImageEvidence(text_marks=4, sharpness=250.0, contrast=40.0)
    svc, vision = _service(ocr_text="", evidence=evidence)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "no_verificable"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_empty_ocr_on_a_blurry_photo_is_sensitive() -> None:
    evidence = ImageEvidence(text_marks=0, sharpness=1.5, contrast=18.0)
    svc, vision = _service(ocr_text="", evidence=evidence)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "no_verificable"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_empty_ocr_on_a_flat_photo_is_sensitive() -> None:
    evidence = ImageEvidence(text_marks=0, sharpness=250.0, contrast=2.0)
    svc, vision = _service(ocr_text="", evidence=evidence)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "no_verificable"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_evidence_probe_unavailable_is_sensitive() -> None:
    svc, vision = _service(ocr_text="", evidence_error=OcrUnavailableError)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "no_legible"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_scarce_ocr_text_on_a_blurry_image_is_sensitive() -> None:
    """M5: el texto escaso también dispara la sonda, no solo el texto vacío."""
    evidence = ImageEvidence(text_marks=0, sharpness=1.5, contrast=40.0)
    svc, vision = _service(ocr_text="FACT", evidence=evidence)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "no_verificable"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_scarce_ocr_text_probe_unavailable_is_sensitive() -> None:
    """Si la sonda tampoco puede correr, el texto escaso no se asume limpio."""
    svc, vision = _service(ocr_text="FACT", evidence_error=OcrUnavailableError)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "no_legible"
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_scarce_ocr_text_on_a_sharp_image_travels() -> None:
    """Un fragmento corto en una foto nítida no se bloquea de más."""
    svc, vision = _service(ocr_text="FACT", evidence=_CLEAN_EVIDENCE)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is False
    assert result.description == "una foto del plato"
    assert vision.calls == 1


@pytest.mark.asyncio
async def test_captioner_failure_is_fail_open() -> None:
    svc, _ = _service(ocr_text="", vision_error=True)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is False
    assert result.description is None


@pytest.mark.asyncio
async def test_redacted_image_describer_failure_is_fail_open() -> None:
    line = OcrLine(
        text="4111 1111 1111 1111", left=10, top=10, width=200, height=30
    )
    svc, _ = _service(
        ocr_text="4111 1111 1111 1111",
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
        text="4111 1111 1111 1111", left=10, top=10, width=300, height=30
    )
    svc, vision = _service(
        ocr_text="4111 1111 1111 1111", lines=(line,), verify_text=""
    )
    result = await svc.analyze(_png_bytes(2000, 1500), mime_type="image/png")
    assert result.sensitive is False
    assert result.masked is True
    with Image.open(io.BytesIO(vision.seen_bytes)) as img:
        assert img.format == "JPEG"
        assert _max_edge(img) <= 1280
    assert vision.seen_mime == "image/jpeg"
