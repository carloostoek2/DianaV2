"""Unit tests for Generator (text LLM → draft only)."""

from __future__ import annotations

import pytest

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
