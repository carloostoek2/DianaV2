"""Unit tests for PII masking (pure functions + DeepSeekProvider wiring).

The provider tests use httpx.MockTransport only — no live network.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from diana.llm.deepseek import DeepSeekProvider
from diana.llm.pii_masker import mask_pii, unmask_pii


class _TinySchema(BaseModel):
    value: str
    count: int


def _openai_chat_response(content: str) -> httpx.Response:
    body = {
        "id": "chatcmpl-pii-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    return httpx.Response(200, json=body)


def _provider_with_transport(
    handler,
    *,
    pii_masking: bool = True,
) -> DeepSeekProvider:
    base_url = "https://api.deepseek.com"
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url=base_url)
    return DeepSeekProvider(
        api_key=SecretStr("test-key"),
        base_url=base_url,
        client=client,
        model="deepseek-chat",
        thinking_enabled=False,
        pii_masking=pii_masking,
    )


# ---------- mask_pii: entities ----------


def test_masks_email() -> None:
    result = mask_pii("escríbeme a maria.lopez@gmail.com por favor")
    assert "maria.lopez@gmail.com" not in result.masked
    assert "[correo]" in result.masked
    assert result.stats == {"correo": 1}
    assert result.mapping["[correo]"] == "maria.lopez@gmail.com"


@pytest.mark.parametrize(
    "phone",
    [
        "55 1234 5678",
        "+52 55 1234 5678",
        "+52 1 55 1234 5678",
        "(55) 1234-5678",
        "5512345678",
        "+34 612 345 678",
    ],
)
def test_masks_phone(phone: str) -> None:
    result = mask_pii(f"mi número es {phone}")
    assert phone not in result.masked
    assert "[telefono]" in result.masked
    assert result.mapping["[telefono]"] == phone


def test_masks_payment_card() -> None:
    result = mask_pii("la tarjeta es 4111 1111 1111 1111, gracias")
    assert "4111 1111 1111 1111" not in result.masked
    assert "[tarjeta]" in result.masked
    assert result.mapping["[tarjeta]"] == "4111 1111 1111 1111"


def test_masks_handle_and_url() -> None:
    result = mask_pii("sígueme en @diana_bot y mira https://ejemplo.com/oferta")
    assert "@diana_bot" not in result.masked
    assert "[usuario]" in result.masked
    assert "https://ejemplo.com/oferta" not in result.masked
    assert "[enlace]" in result.masked
    assert result.stats == {"usuario": 1, "enlace": 1}


def test_masks_multiple_entities_with_numbered_tokens() -> None:
    text = "mail a@x.com y b@y.com, tel 55 1234 5678"
    result = mask_pii(text)
    assert "[correo]" in result.masked and "[correo-1]" in result.masked
    assert "[telefono]" in result.masked
    assert len(result.mapping) == 3


# ---------- mask_pii: no false positives ----------


def test_plain_text_untouched() -> None:
    text = "Hola, ¿cómo estás? El evento es el 2026-08-21 a las 18:30."
    result = mask_pii(text)
    assert result.masked == text
    assert result.mapping == {}
    assert result.stats == {}


def test_short_dates_and_amounts_not_masked() -> None:
    text = "Costo: $1,234.56. Fecha: 2026-08-21."
    result = mask_pii(text)
    assert result.masked == text


def test_non_luhn_digit_run_not_card() -> None:
    # Luhn-invalid 16-digit run must not be labeled a card.
    result = mask_pii("referencia 1234567890123456")
    assert "tarjeta" not in result.stats


# ---------- collision safety / unmask ----------


def test_collision_safe_when_placeholder_already_in_text() -> None:
    text = "mi correo es [correo] pero el real es maria@x.com"
    result = mask_pii(text)
    assert "[correo-1]" in result.masked
    assert result.mapping["[correo-1]"] == "maria@x.com"


def test_unmask_roundtrip_restores_original() -> None:
    original = "escríbeme a maria@x.com o al 55 1234 5678"
    result = mask_pii(original)
    assert unmask_pii(result.masked, result.mapping) == original


def test_unmask_ignores_unknown_tokens() -> None:
    assert unmask_pii("hola [correo]", {}) == "hola [correo]"


def test_mask_empty_text() -> None:
    result = mask_pii("")
    assert result.masked == "" and result.mapping == {} and result.stats == {}


# ---------- DeepSeekProvider wiring ----------


@pytest.mark.asyncio
async def test_generate_masks_outbound_and_unmasks_reply() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured["outbound"] = payload["messages"][0]["content"]
        # The model echoes the placeholder verbatim in its draft.
        return _openai_chat_response("claro, te llamo al [telefono]")

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        text = await provider.generate(
            [{"role": "user", "content": "mi número es +52 55 1234 5678"}]
        )
        assert "+52 55 1234 5678" not in captured["outbound"]
        assert "[telefono]" in captured["outbound"]
        assert text == "claro, te llamo al +52 55 1234 5678"
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_generate_structured_masks_outbound_and_unmasks_fields() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured["outbound"] = payload["messages"][-1]["content"]
        return _openai_chat_response(
            json.dumps({"value": "contacto: [correo]", "count": 1})
        )

    provider = _provider_with_transport(handler)
    client = provider._client
    try:
        result = await provider.generate_structured(
            [{"role": "user", "content": "mail de maria.lopez@gmail.com"}],
            _TinySchema,
        )
        assert "maria.lopez@gmail.com" not in captured["outbound"]
        assert "[correo]" in captured["outbound"]
        assert result.value == "contacto: maria.lopez@gmail.com"
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_pii_masking_can_be_disabled() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured["outbound"] = payload["messages"][0]["content"]
        return _openai_chat_response("ok")

    provider = _provider_with_transport(handler, pii_masking=False)
    client = provider._client
    try:
        await provider.generate(
            [{"role": "user", "content": "mi número es +52 55 1234 5678"}]
        )
        assert "+52 55 1234 5678" in captured["outbound"]
    finally:
        await provider.aclose()
        await client.aclose()
