"""Unit tests for Analyst (structured LLM → Comprehension)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from diana.cognitive.analyst import Analyst
from diana.cognitive.models import Comprehension, IncomingTurn
from diana.llm.fake import FakeLLM


def _turn(text: str = "hola") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text=text)


def _valid_comprehension(**overrides) -> Comprehension:
    data = {
        "intent": "greet",
        "topics": ["hello"],
        "emotion": "friendly",
        "urgency": "baja",
        "risk": "bajo",
        "needs_history": True,
        "needs_context": True,
    }
    data.update(overrides)
    return Comprehension(**data)


@pytest.mark.asyncio
async def test_analyze_returns_comprehension_from_fake_llm() -> None:
    expected = _valid_comprehension(intent="ask_schedule")
    llm = FakeLLM(structured_responses=[expected])
    analyst = Analyst(llm)
    result = await analyst.analyze(_turn("¿cuándo podés?"))
    assert isinstance(result, Comprehension)
    assert result.intent == "ask_schedule"
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == "generate_structured"
    assert llm.calls[0][1]["schema"] is Comprehension


@pytest.mark.asyncio
async def test_analyze_includes_turn_text_in_messages() -> None:
    llm = FakeLLM(structured_responses=[_valid_comprehension()])
    await Analyst(llm).analyze(_turn("unique-vip-text-xyz"))
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages)
    assert "unique-vip-text-xyz" in flat


@pytest.mark.asyncio
async def test_analyze_invalid_structured_payload_raises() -> None:
    llm = FakeLLM(structured_responses=[{"intent": "only"}])
    with pytest.raises(ValidationError):
        await Analyst(llm).analyze(_turn())


@pytest.mark.asyncio
async def test_analyze_uses_only_generate_structured() -> None:
    llm = FakeLLM(
        text_responses=["should-not-use"],
        structured_responses=[_valid_comprehension()],
    )
    await Analyst(llm).analyze(_turn())
    methods = [c[0] for c in llm.calls]
    assert methods == ["generate_structured"]
