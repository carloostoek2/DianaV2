"""ImageVisionService — OCR privacy filter + caption orchestration (unit)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from diana.application.image_vision_service import (
    ImageVisionService,
    classify_sensitive,
    luhn_valid,
)
from diana.cognitive.image_vision import ImageDescriber
from diana.infrastructure.vision.ocr import OcrUnavailableError


def _fake_ocr(text: str | type[Exception]):
    """OcrEngine-compatible fake: returns text or raises."""
    return SimpleNamespace(extract_text=lambda _b: (_raise(text) if isinstance(text, type) else text))


def _raise(exc: type[Exception]) -> None:
    raise exc()


class _FakeVision:
    def __init__(self, text: str | None = None, error: bool = False) -> None:
        self._text = text
        self._error = error

    async def describe_image(self, image_bytes, *, mime_type, prompt) -> str:
        if self._error:
            raise RuntimeError("gemini down")
        return self._text


def _service(*, ocr_text: str = "", vision_text: str = "una foto del plato", enabled: bool = True, vision_error: bool = False) -> ImageVisionService:
    ocr = _fake_ocr(ocr_text)
    describer = ImageDescriber(vision=_FakeVision(vision_text, error=vision_error))
    return ImageVisionService(ocr=ocr, describer=describer, enabled=enabled)


# --- classify_sensitive: pure rules -----------------------------------------

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


# --- ImageVisionService orchestration ---------------------------------------

@pytest.mark.asyncio
async def test_disabled_feature_returns_plain_result() -> None:
    svc = _service(enabled=False)
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
async def test_sensitive_image_never_calls_captioner() -> None:
    svc = _service(ocr_text="FACTURA Total 99.90")
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "factura"
    assert result.description is None


@pytest.mark.asyncio
async def test_ocr_unavailable_is_fail_closed_sensitive() -> None:
    svc = _service(ocr_text=OcrUnavailableError)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is True
    assert result.reason == "no_legible"
    assert result.description is None


@pytest.mark.asyncio
async def test_caption_also_counts_toward_sensitivity() -> None:
    svc = _service(ocr_text="")
    result = await svc.analyze(
        b"img", mime_type="image/jpeg", caption="te mando mi DNI"
    )
    assert result.sensitive is True
    assert result.reason == "identidad"


@pytest.mark.asyncio
async def test_clean_image_gets_caption() -> None:
    svc = _service(ocr_text="", vision_text="una foto del plato")
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is False
    assert result.description == "una foto del plato"


@pytest.mark.asyncio
async def test_captioner_failure_is_fail_open() -> None:
    svc = _service(ocr_text="", vision_error=True)
    result = await svc.analyze(b"img", mime_type="image/jpeg")
    assert result.sensitive is False
    assert result.description is None
