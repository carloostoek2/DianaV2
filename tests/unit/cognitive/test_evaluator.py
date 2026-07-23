"""Unit tests for Evaluator (structured LLM → EvaluationProfile 7D)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from diana.cognitive.evaluator import Evaluator
from diana.cognitive.exceptions import EvaluatorSchemaInvalidError
from diana.cognitive.models import Comprehension, EvaluationProfile, EvaluatorInput
from diana.llm.fake import FakeLLM

_DIMS = (
    "naturalness",
    "precision",
    "doctrine",
    "consistency",
    "safety",
    "coverage",
    "empathy",
)


def _profile(**overrides: float) -> EvaluationProfile:
    data = {d: 0.8 for d in _DIMS}
    data.update(overrides)
    return EvaluationProfile(**data)


def _comprehension(**overrides) -> Comprehension:
    data = dict(
        intent="chat",
        topics=["x"],
        emotion="ansiosa",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
    )
    data.update(overrides)
    return Comprehension(**data)


def _input(**overrides) -> EvaluatorInput:
    data = dict(
        draft="draft text",
        comprehension=_comprehension(),
        included_blocks=["knowledge.history"],
        current_turn="hola",
    )
    data.update(overrides)
    return EvaluatorInput(**data)


@pytest.mark.asyncio
async def test_evaluate_accepts_evaluator_input() -> None:
    expected = _profile(safety=0.91)
    llm = FakeLLM(structured_responses=[expected])
    result = await Evaluator(llm).evaluate(_input(draft="draft text"))
    assert isinstance(result, EvaluationProfile)
    assert result.safety == 0.91
    for dim in _DIMS:
        assert hasattr(result, dim)
    assert llm.calls[0][0] == "generate_structured"
    assert llm.calls[0][1]["schema"] is EvaluationProfile


@pytest.mark.asyncio
async def test_evaluate_returns_seven_dimension_profile() -> None:
    """Backward-compatible name: DTO signature still returns 7D profile."""
    expected = _profile(safety=0.91)
    llm = FakeLLM(structured_responses=[expected])
    result = await Evaluator(llm).evaluate(_input())
    assert isinstance(result, EvaluationProfile)
    assert result.safety == 0.91


@pytest.mark.asyncio
async def test_evaluate_incomplete_dims_raise_validation_error() -> None:
    """After exhausted retries, caller sees typed schema error (not bare ValidationError)."""
    incomplete = {d: 0.5 for d in _DIMS if d != "empathy"}
    llm = FakeLLM(structured_responses=[incomplete, incomplete])
    with pytest.raises(EvaluatorSchemaInvalidError) as ei:
        await Evaluator(llm).evaluate(_input())
    assert str(ei.value) == "evaluador_schema_invalido"
    assert ei.value.reason == "evaluador_schema_invalido"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_evaluate_messages_include_draft_and_turno_and_emotion() -> None:
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate(
        _input(
            draft="UNIQUE-DRAFT-ZZ",
            current_turn="TURNO-ACTUAL-QQ",
            comprehension=_comprehension(emotion="ansiosa"),
        )
    )
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages)
    assert "UNIQUE-DRAFT-ZZ" in flat
    assert "TURNO-ACTUAL-QQ" in flat
    assert "ansiosa" in flat


@pytest.mark.asyncio
async def test_evaluate_includes_draft_in_messages() -> None:
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate(_input(draft="UNIQUE-DRAFT-ZZ"))
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages)
    assert "UNIQUE-DRAFT-ZZ" in flat


@pytest.mark.asyncio
async def test_evaluate_messages_include_bloques_names_not_knowledge_bodies() -> None:
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate(
        _input(included_blocks=["knowledge.history", "knowledge.context"])
    )
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages)
    assert "knowledge.history" in flat
    assert "knowledge.context" in flat
    # Anti-contamination: body markers must not appear (names only in DTO).
    assert "SECRET-HISTORY-BODY" not in flat


@pytest.mark.asyncio
async def test_evaluate_system_prompt_doctrine_guidance_when_policy_absent() -> None:
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate(
        _input(included_blocks=["knowledge.history"])  # no knowledge.policy
    )
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages).lower()
    assert "doctrine" in flat
    assert "0.7" in flat


@pytest.mark.asyncio
async def test_evaluate_retries_once_on_validation_error() -> None:
    incomplete = {d: 0.5 for d in _DIMS if d != "empathy"}
    valid = _profile(safety=0.88)
    llm = FakeLLM(structured_responses=[incomplete, valid])
    result = await Evaluator(llm).evaluate(_input())
    assert result.safety == 0.88
    assert len(llm.calls) == 2
    # Same messages on retry
    assert llm.calls[0][1]["messages"] == llm.calls[1][1]["messages"]


@pytest.mark.asyncio
async def test_evaluate_double_fail_raises_evaluador_schema_invalido() -> None:
    incomplete = {d: 0.5 for d in _DIMS if d != "empathy"}
    llm = FakeLLM(structured_responses=[incomplete, incomplete])
    with pytest.raises(EvaluatorSchemaInvalidError) as ei:
        await Evaluator(llm).evaluate(_input())
    assert str(ei.value) == "evaluador_schema_invalido"
    assert ei.value.reason == "evaluador_schema_invalido"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_evaluate_value_error_is_schema_class_and_retries() -> None:
    """ValueError (e.g. DeepSeek JSON) is schema-class; retry then typed error."""
    class BoomLLM(FakeLLM):
        def __init__(self) -> None:
            super().__init__(structured_responses=[])
            self._n = 0

        async def generate_structured(self, messages, schema, **kwargs):  # type: ignore[no-untyped-def]
            self._n += 1
            self.calls.append(
                ("generate_structured", {"messages": messages, "schema": schema})
            )
            raise ValueError("invalid json from provider")

    llm = BoomLLM()
    with pytest.raises(EvaluatorSchemaInvalidError):
        await Evaluator(llm).evaluate(_input())
    assert llm._n == 2  # noqa: SLF001


@pytest.mark.asyncio
async def test_evaluator_field_names_are_english_only() -> None:
    """Spanish SPEC dim names must not appear as model fields."""
    field_names = set(EvaluationProfile.model_fields.keys())
    assert {"naturalness", "safety", "empathy"}.issubset(field_names)
    assert "seguridad" not in field_names
    assert "naturalidad" not in field_names


def test_evaluator_schema_invalid_error_str_and_reason() -> None:
    err = EvaluatorSchemaInvalidError()
    assert str(err) == "evaluador_schema_invalido"
    assert err.reason == "evaluador_schema_invalido"
