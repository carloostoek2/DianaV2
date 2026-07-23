"""Unit tests for Generator (text LLM → draft only; Anexo E)."""

from __future__ import annotations

import pytest

from diana.cognitive.exceptions import GeneratorEmptyOutputError
from diana.cognitive.generator import Generator
from diana.llm.fake import FakeLLM


@pytest.mark.asyncio
async def test_generate_returns_draft_text() -> None:
    llm = FakeLLM(text_responses=["Hola, ¿cómo estás?"])
    draft = await Generator(llm).generate("prompt body")
    assert draft == "Hola, ¿cómo estás?"


@pytest.mark.asyncio
async def test_generate_passes_prompt_to_llm() -> None:
    llm = FakeLLM(text_responses=["draft"])
    await Generator(llm).generate("SPECIAL-PROMPT-CONTENT")
    assert llm.calls[0][0] == "generate"
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages)
    assert "SPECIAL-PROMPT-CONTENT" in flat


@pytest.mark.asyncio
async def test_generate_uses_only_generate_not_structured() -> None:
    llm = FakeLLM(text_responses=["ok"])
    await Generator(llm).generate("p")
    assert [c[0] for c in llm.calls] == ["generate"]


@pytest.mark.asyncio
async def test_generate_system_prompt_is_owner_reply_question() -> None:
    """E.1: system prompt answers only 'how would the owner reply?'."""
    llm = FakeLLM(text_responses=["draft ok"])
    prompt = "PROMPT-FINAL-UNMODIFIED-XYZ"
    await Generator(llm).generate(prompt)
    messages = llm.calls[0][1]["messages"]
    assert messages[0]["role"] == "system"
    system = messages[0]["content"].lower()
    assert "owner" in system and "reply" in system
    # E.1 / REQ-COG-07: system must explicitly forbid classify/search/score/action.
    assert "do not classify" in system
    assert "search knowledge" in system
    assert "score" in system
    assert "choose system actions" in system
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == prompt  # prompt_final unmodified


@pytest.mark.asyncio
async def test_generate_empty_then_success_retries_once() -> None:
    """E.4: empty first response → one retry → return second non-empty."""
    llm = FakeLLM(text_responses=["", "Hola ok"])
    draft = await Generator(llm).generate("same-prompt")
    assert draft == "Hola ok"
    generate_calls = [c for c in llm.calls if c[0] == "generate"]
    assert len(generate_calls) == 2
    for call in generate_calls:
        user = call[1]["messages"][1]["content"]
        assert user == "same-prompt"


@pytest.mark.asyncio
async def test_generate_whitespace_then_success_retries_once() -> None:
    """E.4: whitespace-only counts as empty; retry once then success."""
    llm = FakeLLM(text_responses=["   \n", "draft"])
    draft = await Generator(llm).generate("p")
    assert draft == "draft"
    assert len([c for c in llm.calls if c[0] == "generate"]) == 2


@pytest.mark.asyncio
async def test_generate_double_empty_raises_generador_salida_vacia() -> None:
    """E.4: permanent empty → GeneratorEmptyOutputError after exactly 2 calls."""
    llm = FakeLLM(text_responses=["", "  "])
    with pytest.raises(GeneratorEmptyOutputError) as ei:
        await Generator(llm).generate("p")
    assert str(ei.value) == "generador_salida_vacia"
    assert ei.value.reason == "generador_salida_vacia"
    assert len([c for c in llm.calls if c[0] == "generate"]) == 2


@pytest.mark.asyncio
async def test_generate_transport_error_does_not_count_as_empty_retry() -> None:
    """Transport/runtime errors propagate; not swallowed as empty-class retry."""
    llm = FakeLLM(text_responses=[])  # empty queue → RuntimeError on first generate
    with pytest.raises(RuntimeError, match="FakeLLM text response queue is empty"):
        await Generator(llm).generate("p")
    assert len([c for c in llm.calls if c[0] == "generate"]) == 1


def test_generator_empty_output_error_str_and_reason() -> None:
    err = GeneratorEmptyOutputError()
    assert str(err) == "generador_salida_vacia"
    assert err.reason == "generador_salida_vacia"
