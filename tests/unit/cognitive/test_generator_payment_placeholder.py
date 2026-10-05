"""Generator pastes masked business payment data (``[tarjeta]``) on payment asks.

Production bug: the persona fact ``metodos_pago`` (atencion channel) carries
the business card number, bank and holder name. The PII masker replaces the
card number with ``[tarjeta]`` before the prompt leaves the process and
restores it on the reply ONLY if the model echoes the placeholder verbatim.
The model treated the placeholder as redacted and answered "te paso los
datos" without pasting them, so the client never received the account.

These tests pin (1) the Generator system instruction and (2) the end-to-end
contract through the real provider masking: an echoed placeholder becomes the
real card number in the draft; the card number never crosses to the provider.
Card numbers used here are public test numbers, never real data.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from diana.cognitive.context_builder import _knowledge_section_parts
from diana.cognitive.generator import (
    _HARD_BAN_RULE,
    _PAYMENT_PLACEHOLDER_RULE,
    _SYSTEM,
    Generator,
)
from diana.llm.deepseek import DeepSeekProvider
from diana.llm.fake import FakeLLM
from diana.llm.pii_masker import mask_pii

_TEST_PAN = "4111 1111 1111 1111"  # public Visa test number (Luhn-valid)
_BANK = "Banco Ejemplo"
_HOLDER = "Nombre Titular"

_METODOS_PAGO_FACT = {
    "hecho": (
        "Los pagos se hacen por transferencia; Diana confirma personalmente.\n"
        "Los datos son: \n"
        f"Número de tarjeta (débito): {_TEST_PAN}\n"
        f"Banco: {_BANK}\n"
        f"Nombre: {_HOLDER}"
    ),
    "tema": "pago",
}


def _payment_prompt() -> str:
    """User prompt shaped like ContextBuilder output for a payment ask."""
    parts, included = _knowledge_section_parts(
        {"knowledge.persona_facts": [_METODOS_PAGO_FACT]}
    )
    assert included == ["knowledge.persona_facts"]
    return "\n".join(
        ["## Turno actual", "Cliente: hola, cómo te pago?", *parts]
    )


# ---------- 1. system instruction ----------


@pytest.mark.asyncio
async def test_system_prompt_carries_payment_placeholder_rule() -> None:
    llm = FakeLLM(text_responses=["draft ok"])
    await Generator(llm).generate("prompt body")
    system = llm.calls[0][1]["messages"][0]["content"]
    assert _PAYMENT_PLACEHOLDER_RULE in system
    low = system.lower()
    assert "[tarjeta]" in system
    assert "exactly as written" in low
    assert "banco" in low and "nombre" in low
    assert "same message" in low
    # Explicitly forbids the "te paso los datos" non-answer.
    assert "te paso los datos" in low
    assert "without including them" in low
    # Single method → give it, don't ask which one they prefer.
    assert "instead of asking which method" in low
    # No hallucinated placeholders / data.
    assert "never invent card numbers" in low
    assert "placeholder that does not appear in the prompt" in low


def test_payment_rule_precedes_output_instruction_and_safety() -> None:
    assert _SYSTEM.index("PAYMENT DATA") < _SYSTEM.index("SAFETY")
    assert _SYSTEM.index("PAYMENT DATA") < _SYSTEM.index("Output the draft text only")


def test_payment_rule_not_in_shared_evaluator_ban() -> None:
    """The Evaluator imports only _HARD_BAN_RULE; it must stay unchanged."""
    assert "[tarjeta]" not in _HARD_BAN_RULE
    assert "PAYMENT DATA" not in _HARD_BAN_RULE


# ---------- 2. end-to-end masking contract ----------


def _openai_chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-pay",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def _provider(handler) -> DeepSeekProvider:
    base_url = "https://api.deepseek.com"
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=base_url
    )
    return DeepSeekProvider(
        api_key=SecretStr("test-key"),
        base_url=base_url,
        client=client,
        model="deepseek-chat",
        thinking_enabled=False,
        pii_masking=True,
    )


def test_knowledge_render_masks_card_as_tarjeta_placeholder() -> None:
    """The rendered metodos_pago fact masks the card to the exact token the
    system rule names; bank and holder name stay in clear text."""
    result = mask_pii(_payment_prompt())
    assert _TEST_PAN not in result.masked
    assert "[tarjeta]" in result.masked
    assert result.mapping["[tarjeta]"] == _TEST_PAN
    assert _BANK in result.masked and _HOLDER in result.masked


@pytest.mark.asyncio
async def test_echoed_placeholder_becomes_real_card_in_draft() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured["system"] = payload["messages"][0]["content"]
        captured["user"] = payload["messages"][1]["content"]
        # Model follows the rule: pastes the placeholder + bank + holder.
        return _openai_chat_response(
            "Con gusto, el pago es por transferencia. Tarjeta: [tarjeta], "
            f"{_BANK}, a nombre de {_HOLDER}. Cuando lo hagas me avisas para "
            "confirmarlo?"
        )

    provider = _provider(handler)
    client = provider._client
    try:
        draft = await Generator(provider).generate(_payment_prompt())
    finally:
        await provider.aclose()
        await client.aclose()

    # Card number never crosses the trust boundary...
    assert _TEST_PAN not in captured["user"]
    assert "[tarjeta]" in captured["user"]
    assert "PAYMENT DATA" in captured["system"]
    # ...and the client still receives it, with bank and holder.
    assert _TEST_PAN in draft
    assert "[tarjeta]" not in draft
    assert _BANK in draft and _HOLDER in draft


@pytest.mark.asyncio
async def test_promise_without_placeholder_delivers_no_card() -> None:
    """Documents the bug the rule prevents: a reply that only promises the
    data carries no card number (nothing to unmask)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_chat_response("Claro, ahorita te paso los datos para pagar")

    provider = _provider(handler)
    client = provider._client
    try:
        draft = await Generator(provider).generate(_payment_prompt())
    finally:
        await provider.aclose()
        await client.aclose()
    assert _TEST_PAN not in draft


# ---------- 3. static atencion seed (fallback + fresh installs) ----------

_ATENCION_JSON = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "diana"
    / "config"
    / "persona_atencion.json"
)


def _atencion_catalog() -> dict:
    return json.loads(_ATENCION_JSON.read_text(encoding="utf-8"))


def test_seed_datos_pago_policy_requires_full_data_same_message() -> None:
    policy = next(
        p for p in _atencion_catalog()["policies"] if p["id"] == "datos_pago"
    )
    regla = policy["regla"].lower()
    for token in ("tarjeta", "banco", "nombre", "mismo mensaje"):
        assert token in regla
    assert "sin prometer mandarlos después" in regla
    assert "nunca inventes" in regla


def test_seed_clarificacion_pago_no_longer_asks_preferred_method() -> None:
    pattern = next(
        v
        for v in _atencion_catalog()["voice_patterns"]
        if v["id"] == "clarificacion_pago"
    )
    assert "prefieres" not in pattern["patron"].lower()
    assert "?" not in pattern["patron"]
    assert "no se pregunta" in pattern["uso"].lower()


def test_seed_never_ships_a_card_number() -> None:
    """Real payment data lives only in the DB persona (owner panel)."""
    assert "tarjeta" not in mask_pii(_ATENCION_JSON.read_text(encoding="utf-8")).stats
