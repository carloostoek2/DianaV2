"""Unit tests for Evaluator (structured LLM → EvaluationProfile 7D)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from diana.cognitive.evaluator import Evaluator
from diana.cognitive.models import Comprehension, EvaluationProfile, IncomingTurn
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


def _turn() -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text="hola")


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="chat",
        topics=["x"],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
    )


@pytest.mark.asyncio
async def test_evaluate_returns_seven_dimension_profile() -> None:
    expected = _profile(safety=0.91)
    llm = FakeLLM(structured_responses=[expected])
    result = await Evaluator(llm).evaluate("draft text", _comprehension(), _turn())
    assert isinstance(result, EvaluationProfile)
    assert result.safety == 0.91
    for dim in _DIMS:
        assert hasattr(result, dim)
    assert llm.calls[0][0] == "generate_structured"
    assert llm.calls[0][1]["schema"] is EvaluationProfile


@pytest.mark.asyncio
async def test_evaluate_incomplete_dims_raise_validation_error() -> None:
    incomplete = {d: 0.5 for d in _DIMS if d != "empathy"}
    llm = FakeLLM(structured_responses=[incomplete])
    with pytest.raises(ValidationError):
        await Evaluator(llm).evaluate("draft", _comprehension(), _turn())


@pytest.mark.asyncio
async def test_evaluate_includes_draft_in_messages() -> None:
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate("UNIQUE-DRAFT-ZZ", _comprehension(), _turn())
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages)
    assert "UNIQUE-DRAFT-ZZ" in flat


@pytest.mark.asyncio
async def test_evaluator_field_names_are_english_only() -> None:
    """Spanish SPEC dim names must not appear as model fields."""
    spanish = {
        "naturalidad",
        "precision",
        "doctrina",
        "consistencia",
        "seguridad",
        "cobertura",
        "empatia",
    }
    field_names = set(EvaluationProfile.model_fields.keys())
    # English canonical set is what the evaluator produces
    assert {"naturalness", "safety", "empathy"}.issubset(field_names)
    assert "seguridad" not in field_names
    assert "naturalidad" not in field_names
