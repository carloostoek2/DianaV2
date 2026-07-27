"""Unit tests for Analyst (structured LLM → Comprehension)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from diana.cognitive.analyst import Analyst
from diana.cognitive.exceptions import AnalystSchemaInvalidError
from diana.cognitive.models import AnalystInput, Comprehension, HistoryMessage
from diana.llm.fake import FakeLLM


def _input(
    text: str = "hola",
    history: list[HistoryMessage] | None = None,
) -> AnalystInput:
    return AnalystInput(
        turno_actual=text,
        historial_reciente=history if history is not None else [],
    )


def _valid_comprehension(**overrides) -> Comprehension:
    data = {
        "intent": "greet",
        "topics": ["hello"],
        "emotion": "positiva",
        "urgency": "baja",
        "risk": "bajo",
        "needs_memory": False,
        "needs_policy": False,
        "needs_schedule": False,
        "needs_examples": False,
        "needs_history": True,
        "needs_context": True,
    }
    data.update(overrides)
    return Comprehension(**data)


def _invalid_payload() -> dict:
    return {"intent": "only"}


@pytest.mark.asyncio
async def test_analyze_returns_comprehension_from_fake_llm() -> None:
    expected = _valid_comprehension(intent="ask_schedule")
    llm = FakeLLM(structured_responses=[expected])
    analyst = Analyst(llm)
    result = await analyst.analyze(_input("¿cuándo podés?"))
    assert isinstance(result, Comprehension)
    assert result.intent == "ask_schedule"
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == "generate_structured"
    assert llm.calls[0][1]["schema"] is Comprehension


@pytest.mark.asyncio
async def test_analyze_includes_turn_text_in_messages() -> None:
    llm = FakeLLM(structured_responses=[_valid_comprehension()])
    await Analyst(llm).analyze(_input("unique-vip-text-xyz"))
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages)
    assert "unique-vip-text-xyz" in flat


@pytest.mark.asyncio
async def test_analyze_includes_historial_reciente_not_memory() -> None:
    history = [
        HistoryMessage(
            autor="vip",
            texto="prior-vip-line-AAA",
            timestamp="2026-01-01T10:00:00Z",
        ),
        HistoryMessage(
            autor="dueña",
            texto="prior-owner-line-BBB",
            timestamp="2026-01-01T10:01:00Z",
        ),
    ]
    llm = FakeLLM(structured_responses=[_valid_comprehension()])
    await Analyst(llm).analyze(_input("current-turn-CCC", history=history))
    messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in messages)
    assert "prior-vip-line-AAA" in flat
    assert "prior-owner-line-BBB" in flat
    assert "dueña" in flat or "duena" in flat or "autor" in flat
    assert "current-turn-CCC" in flat
    # Anti-contamination: Analyst input is only turn + history — no memory/policy blobs.
    assert "knowledge.memory" not in flat
    assert "knowledge.policy" not in flat
    assert "vip_id" not in flat


@pytest.mark.asyncio
async def test_analyze_retries_once_on_validation_error() -> None:
    valid = _valid_comprehension(intent="recovered")
    llm = FakeLLM(structured_responses=[_invalid_payload(), valid])
    result = await Analyst(llm).analyze(_input())
    assert result.intent == "recovered"
    assert len(llm.calls) == 2
    assert all(c[0] == "generate_structured" for c in llm.calls)
    # A.6: single retry uses the same input messages.
    assert llm.calls[0][1]["messages"] == llm.calls[1][1]["messages"]


@pytest.mark.asyncio
async def test_analyze_double_fail_raises_analista_schema_invalido() -> None:
    llm = FakeLLM(
        structured_responses=[_invalid_payload(), _invalid_payload()]
    )
    with pytest.raises(AnalystSchemaInvalidError) as exc_info:
        await Analyst(llm).analyze(_input())
    assert str(exc_info.value) == "analista_schema_invalido"
    assert exc_info.value.reason == "analista_schema_invalido"
    assert len(llm.calls) == 2
    assert llm.calls[0][1]["messages"] == llm.calls[1][1]["messages"]


class _ScriptedStructuredLLM:
    """LLM double that raises or returns scripted structured outcomes."""

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
async def test_analyze_retries_once_on_value_error() -> None:
    """DeepSeek-style JSON ValueError is a schema-class failure (A.6)."""
    valid = _valid_comprehension(intent="from-valueerror-retry")
    llm = _ScriptedStructuredLLM(
        [ValueError("assistant content is not valid JSON"), valid]
    )
    result = await Analyst(llm).analyze(_input())  # type: ignore[arg-type]
    assert result.intent == "from-valueerror-retry"
    assert len(llm.calls) == 2
    assert llm.calls[0][1]["messages"] == llm.calls[1][1]["messages"]


@pytest.mark.asyncio
async def test_analyze_valueerror_double_fail_raises_analista_schema_invalido() -> None:
    llm = _ScriptedStructuredLLM(
        [
            ValueError("assistant content is not valid JSON"),
            ValueError("structured response must be a JSON object"),
        ]
    )
    with pytest.raises(AnalystSchemaInvalidError) as exc_info:
        await Analyst(llm).analyze(_input())  # type: ignore[arg-type]
    assert str(exc_info.value) == "analista_schema_invalido"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_analyze_timeout_maps_to_analista_schema_invalido() -> None:
    """A.6.4: timeout follows the same typed fail path after one retry."""
    llm = _ScriptedStructuredLLM([TimeoutError("llm timeout"), TimeoutError("again")])
    with pytest.raises(AnalystSchemaInvalidError) as exc_info:
        await Analyst(llm).analyze(_input())  # type: ignore[arg-type]
    assert str(exc_info.value) == "analista_schema_invalido"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_analyze_non_schema_errors_propagate_without_retry() -> None:
    llm = _ScriptedStructuredLLM([RuntimeError("provider 500")])
    with pytest.raises(RuntimeError, match="provider 500"):
        await Analyst(llm).analyze(_input())  # type: ignore[arg-type]
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_analyze_invalid_structured_payload_raises() -> None:
    """After exhausted retries, typed error (not bare ValidationError)."""
    llm = FakeLLM(
        structured_responses=[_invalid_payload(), _invalid_payload()]
    )
    with pytest.raises(AnalystSchemaInvalidError):
        await Analyst(llm).analyze(_input())
    with pytest.raises(ValidationError):
        # Control: raw invalid still fails pydantic when validated directly
        Comprehension.model_validate(_invalid_payload())


@pytest.mark.asyncio
async def test_analyze_uses_only_generate_structured() -> None:
    llm = FakeLLM(
        text_responses=["should-not-use"],
        structured_responses=[_valid_comprehension()],
    )
    await Analyst(llm).analyze(_input())
    methods = [c[0] for c in llm.calls]
    assert methods == ["generate_structured"]


@pytest.mark.asyncio
async def test_analyze_attaches_raw_llm_output() -> None:
    expected = _valid_comprehension(intent="ask")
    llm = FakeLLM(structured_responses=[expected])
    result = await Analyst(llm).analyze(_input())
    assert result.raw_llm_output is not None
    assert result.raw_llm_output["intent"] == "ask"


@pytest.mark.asyncio
async def test_analyze_system_prompt_has_no_tone_or_policy_instructions() -> None:
    llm = FakeLLM(structured_responses=[_valid_comprehension()])
    await Analyst(llm).analyze(_input())
    messages = llm.calls[0][1]["messages"]
    system = next(m["content"] for m in messages if m.get("role") == "system")
    lowered = system.lower()
    blocked = (
        "tone",
        "style",
        "pricing",
        "write like",
        "how to reply",
        "write a reply",
        "business rule",
        "pricing rules",
        "tono",
        "estilo",
        "precios",
        "cómo responder",
        "como responder",
    )
    for word in blocked:
        assert word not in lowered, f"blocked instruction found: {word!r}"
    # Closed enums present
    assert "neutral" in lowered
    assert "positiva" in lowered
    assert "cariñosa" in lowered or "carinosa" in lowered
    assert "baja" in lowered
    assert "bajo" in lowered



def test_system_prompt_mentions_persona_voice_needs() -> None:
    """H2: Analyst _SYSTEM lists new needs_* flags and usage hints."""
    from diana.cognitive import analyst as analyst_mod

    system = analyst_mod._SYSTEM
    assert "needs_persona_facts" in system
    assert "needs_voice_patterns" in system
    assert "needs_profile" in system
    # usage hints (bio / voice / policy / permanent profile) + catalog tema tokens
    low = system.lower()
    assert "persona" in low or "bio" in low or "biogr" in low
    assert "voice" in low or "muletilla" in low
    assert "permanent" in low or "prefer" in low or "standing" in low
    assert "needs_policy" in system
    assert "familia" in low
    assert "contenido" in low
    assert "cariñosa" in low or "carinosa" in low


def test_system_prompt_mentions_current_activity_needs_schedule() -> None:
    """H9.6: needs_schedule for current-activity questions (qué haces ahora)."""
    from diana.cognitive import analyst as analyst_mod

    system = analyst_mod._SYSTEM
    assert "needs_schedule" in system
    low = system.lower()
    assert "qué haces" in low or "que haces" in low
    assert "current" in low or "ahora" in low or "activity" in low
