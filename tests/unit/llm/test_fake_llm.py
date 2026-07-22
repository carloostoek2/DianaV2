"""Unit tests for FakeLLM — scriptable test double for cognitive suite."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from diana.llm.fake import FakeLLM


class _TinySchema(BaseModel):
    value: str
    count: int


@pytest.mark.asyncio
async def test_fake_llm_generate_returns_queued_text() -> None:
    llm = FakeLLM(text_responses=["hello draft", "second"])
    assert await llm.generate([{"role": "user", "content": "hi"}]) == "hello draft"
    assert await llm.generate([{"role": "user", "content": "again"}]) == "second"


@pytest.mark.asyncio
async def test_fake_llm_generate_structured_returns_model() -> None:
    expected = _TinySchema(value="ok", count=3)
    llm = FakeLLM(structured_responses=[expected])
    result = await llm.generate_structured(
        [{"role": "user", "content": "parse"}],
        _TinySchema,
    )
    assert isinstance(result, _TinySchema)
    assert result == expected


@pytest.mark.asyncio
async def test_fake_llm_records_calls() -> None:
    llm = FakeLLM(
        text_responses=["draft"],
        structured_responses=[_TinySchema(value="a", count=1)],
    )
    messages = [{"role": "user", "content": "x"}]
    await llm.generate(messages, temperature=0.2, max_tokens=64)
    await llm.generate_structured(messages, _TinySchema, temperature=0.0)

    assert len(llm.calls) == 2
    assert llm.calls[0][0] == "generate"
    assert llm.calls[0][1]["messages"] == messages
    assert llm.calls[0][1]["temperature"] == 0.2
    assert llm.calls[0][1]["max_tokens"] == 64
    assert llm.calls[1][0] == "generate_structured"
    assert llm.calls[1][1]["schema"] is _TinySchema


@pytest.mark.asyncio
async def test_fake_llm_raises_when_text_queue_empty() -> None:
    llm = FakeLLM(text_responses=[])
    with pytest.raises(RuntimeError, match="text"):
        await llm.generate([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_fake_llm_raises_when_structured_queue_empty() -> None:
    llm = FakeLLM(structured_responses=[])
    with pytest.raises(RuntimeError, match="structured"):
        await llm.generate_structured([{"role": "user", "content": "x"}], _TinySchema)


@pytest.mark.asyncio
async def test_fake_llm_structured_dict_validates_into_schema() -> None:
    llm = FakeLLM(structured_responses=[{"value": "from-dict", "count": 2}])
    result = await llm.generate_structured(
        [{"role": "user", "content": "x"}],
        _TinySchema,
    )
    assert result == _TinySchema(value="from-dict", count=2)


@pytest.mark.asyncio
async def test_fake_llm_structured_invalid_dict_raises_validation_error() -> None:
    llm = FakeLLM(structured_responses=[{"value": "missing-count"}])
    with pytest.raises(ValidationError):
        await llm.generate_structured(
            [{"role": "user", "content": "x"}],
            _TinySchema,
        )


def test_fake_llm_name() -> None:
    llm = FakeLLM()
    assert llm.name == "fake"
