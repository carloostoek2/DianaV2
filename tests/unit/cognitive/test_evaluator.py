"""Unit tests for Evaluator (structured LLM → EvaluationProfile 7D)."""

from __future__ import annotations

import json

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

# Distinctive B.3 doctrine-guidance tokens (must not fire when policy is included).
_DOCTRINE_GUIDANCE_TOKENS = (
    "approximately 0.7",
    "neutral-high",
    "not among included_blocks",
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


class _ScriptedStructuredLLM:
    """LLM double that raises or returns scripted structured outcomes (Analyst parity)."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, dict]] = []

    async def generate_structured(self, messages, schema, **kwargs):  # noqa: ANN001
        self.calls.append(
            ("generate_structured", {"messages": messages, "schema": schema})
        )
        if not self._outcomes:
            raise RuntimeError("scripted LLM queue empty")
        item = self._outcomes.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


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
async def test_evaluate_attaches_raw_llm_output_when_missing() -> None:
    """Happy path fills raw_llm_output when the structured model omits it."""
    llm = FakeLLM(structured_responses=[_profile(safety=0.77)])
    result = await Evaluator(llm).evaluate(_input())
    assert result.raw_llm_output is not None
    for dim in _DIMS:
        assert dim in result.raw_llm_output
    assert result.raw_llm_output["safety"] == 0.77


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
async def test_evaluate_system_penalizes_mexican_slang_and_profanity() -> None:
    """Communication standard: slang/profanity must lower naturalness (and related dims)."""
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate(_input())
    messages = llm.calls[0][1]["messages"]
    system = next(m["content"] for m in messages if m["role"] == "system").lower()
    assert "mexican slang" in system or "slang mexicano" in system
    assert "profan" in system or "swear" in system or "vulgar" in system
    assert "naturalness" in system


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
    """Names-only payload: included_blocks JSON list + public comprehension; no raw dump."""
    secret_blob = {"marker": "SECRET-RAW-LLM-BLOB-ZZ", "nested": True}
    compr = _comprehension().model_copy(update={"raw_llm_output": secret_blob})
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate(
        _input(
            included_blocks=["knowledge.history", "knowledge.context"],
            comprehension=compr,
        )
    )
    messages = llm.calls[0][1]["messages"]
    user = next(m["content"] for m in messages if m["role"] == "user")
    flat = " ".join(m.get("content", "") for m in messages)
    assert "knowledge.history" in flat
    assert "knowledge.context" in flat
    # Structural: included_blocks serialized as JSON name list only.
    assert '"included_blocks"' in user or "included_blocks:" in user
    assert "knowledge.history" in user
    # Public comprehension fields present; raw_llm_output blob excluded from LLM payload.
    assert "ansiosa" in user
    assert "intent" in user
    assert "SECRET-RAW-LLM-BLOB-ZZ" not in flat
    assert "raw_llm_output" not in flat


@pytest.mark.asyncio
async def test_evaluate_system_prompt_doctrine_guidance_when_policy_absent() -> None:
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate(
        _input(included_blocks=["knowledge.history"])  # no knowledge.policy
    )
    messages = llm.calls[0][1]["messages"]
    system = next(m["content"] for m in messages if m["role"] == "system")
    system_l = system.lower()
    # Distinctive B.3 tokens (not bare "doctrine" from the 7D list).
    assert "approximately 0.7" in system_l
    assert "neutral-high" in system_l
    assert "not among included_blocks" in system_l


@pytest.mark.asyncio
async def test_evaluate_system_prompt_no_neutral_doctrine_when_policy_included() -> None:
    llm = FakeLLM(structured_responses=[_profile()])
    await Evaluator(llm).evaluate(
        _input(included_blocks=["knowledge.history", "knowledge.policy"])
    )
    messages = llm.calls[0][1]["messages"]
    system = next(m["content"] for m in messages if m["role"] == "system")
    system_l = system.lower()
    for token in _DOCTRINE_GUIDANCE_TOKENS:
        assert token not in system_l


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
    llm = _ScriptedStructuredLLM(
        [
            ValueError("invalid json from provider"),
            ValueError("still invalid"),
        ]
    )
    with pytest.raises(EvaluatorSchemaInvalidError) as ei:
        await Evaluator(llm).evaluate(_input())  # type: ignore[arg-type]
    assert str(ei.value) == "evaluador_schema_invalido"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_evaluate_retries_once_on_value_error_then_succeeds() -> None:
    """ValueError then valid profile recovers on second attempt."""
    valid = _profile(safety=0.66)
    llm = _ScriptedStructuredLLM(
        [ValueError("assistant content is not valid JSON"), valid]
    )
    result = await Evaluator(llm).evaluate(_input())  # type: ignore[arg-type]
    assert result.safety == 0.66
    assert len(llm.calls) == 2
    assert llm.calls[0][1]["messages"] == llm.calls[1][1]["messages"]


@pytest.mark.asyncio
async def test_evaluate_timeout_maps_to_evaluador_schema_invalido() -> None:
    """B.6: TimeoutError is schema-class; typed fail after one retry."""
    llm = _ScriptedStructuredLLM([TimeoutError("llm timeout"), TimeoutError("again")])
    with pytest.raises(EvaluatorSchemaInvalidError) as ei:
        await Evaluator(llm).evaluate(_input())  # type: ignore[arg-type]
    assert str(ei.value) == "evaluador_schema_invalido"
    assert ei.value.reason == "evaluador_schema_invalido"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_evaluate_non_schema_errors_propagate_without_retry() -> None:
    """Non-schema provider errors must not be washed by the B.6 retry loop."""
    llm = _ScriptedStructuredLLM([RuntimeError("provider 500")])
    with pytest.raises(RuntimeError, match="provider 500"):
        await Evaluator(llm).evaluate(_input())  # type: ignore[arg-type]
    assert len(llm.calls) == 1


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

@pytest.mark.asyncio
async def test_evaluate_payload_includes_persona_voice_needs_flags() -> None:
    """User payload JSON includes needs_persona_facts / needs_voice_patterns (true and false)."""
    llm = FakeLLM(structured_responses=[_profile(), _profile()])
    evaluator = Evaluator(llm)

    await evaluator.evaluate(
        _input(
            comprehension=_comprehension(
                needs_persona_facts=True,
                needs_voice_patterns=False,
            )
        )
    )
    user_true = next(m["content"] for m in llm.calls[0][1]["messages"] if m["role"] == "user")
    # Extract comprehension JSON object from user payload.
    marker = "comprehension:\n"
    assert marker in user_true
    rest = user_true.split(marker, 1)[1]
    compr_json = rest.split("\n\nincluded_blocks:", 1)[0]
    data = json.loads(compr_json)
    assert data["needs_persona_facts"] is True
    assert data["needs_voice_patterns"] is False
    assert data["needs_context"] is True

    await evaluator.evaluate(
        _input(
            comprehension=_comprehension(
                needs_persona_facts=False,
                needs_voice_patterns=True,
            )
        )
    )
    user_false = next(m["content"] for m in llm.calls[1][1]["messages"] if m["role"] == "user")
    rest2 = user_false.split(marker, 1)[1]
    data2 = json.loads(rest2.split("\n\nincluded_blocks:", 1)[0])
    assert data2["needs_persona_facts"] is False
    assert data2["needs_voice_patterns"] is True


def test_comprehension_helper_defaults_new_needs_flags_false() -> None:
    """_comprehension() still works; new needs_* fields default False via model."""
    c = _comprehension()
    assert c.needs_persona_facts is False
    assert c.needs_voice_patterns is False

