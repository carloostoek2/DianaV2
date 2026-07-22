"""Integration tests for CognitiveDirector deterministic pipeline."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import CognitiveDirector
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.models import (
    Comprehension,
    Decision,
    EvaluationProfile,
    IncomingTurn,
    TurnStatus,
)
from diana.cognitive.planner import Planner
from diana.cognitive.ports import (
    TRACE_KEYS,
    InMemoryMessageHistory,
    InMemoryTraceStore,
    InMemoryTurnStatusSink,
)
from diana.cognitive.registry import build_default_registry
from diana.llm.fake import FakeLLM


def _profile(**overrides: float) -> EvaluationProfile:
    data = {
        "naturalness": 0.9,
        "precision": 0.8,
        "doctrine": 0.85,
        "consistency": 0.9,
        "safety": 0.95,
        "coverage": 0.7,
        "empathy": 0.8,
    }
    data.update(overrides)
    return EvaluationProfile(**data)


def _comprehension(**overrides) -> Comprehension:
    data = {
        "intent": "chat",
        "topics": ["general"],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        "needs_history": True,
        "needs_context": True,
        "needs_memory": False,
        "needs_policy": False,
        "needs_examples": False,
        "needs_schedule": False,
    }
    data.update(overrides)
    return Comprehension(**data)


def _turn(*, chat_id: int = 42, text: str = "hola Diana") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=chat_id, text=text)


def make_director(
    fake_llm: FakeLLM,
    *,
    history_port: InMemoryMessageHistory | None = None,
    status_sink: InMemoryTurnStatusSink | None = None,
    thresholds: dict | None = None,
    persona: str = "You are Diana.",
) -> tuple[CognitiveDirector, InMemoryTraceStore, InMemoryMessageHistory]:
    history = history_port or InMemoryMessageHistory()
    trace = InMemoryTraceStore()
    director = CognitiveDirector(
        analyst=Analyst(fake_llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=ContextBuilder(),
        generator=Generator(fake_llm),
        evaluator=Evaluator(fake_llm),
        decider=Decider(thresholds=thresholds),
        trace=trace,
        persona=persona,
        status_sink=status_sink,
    )
    return director, trace, history


@pytest.mark.asyncio
async def test_happy_path_approve() -> None:
    llm = FakeLLM(
        structured_responses=[
            _comprehension(risk="medio"),
            _profile(safety=0.5),
        ],
        text_responses=["Draft reply for VIP"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    decision = await director.handle_turn(turn)

    assert isinstance(decision, Decision)
    assert decision.action == "approve"
    assert decision.reason == "ok_for_human_review"
    assert decision.draft_text == "Draft reply for VIP"
    assert decision.draft_text  # non-empty


@pytest.mark.asyncio
async def test_escalate_safety_below_threshold() -> None:
    llm = FakeLLM(
        structured_responses=[
            _comprehension(risk="bajo"),
            _profile(safety=0.1),
        ],
        text_responses=["Risky draft"],
    )
    director, _, _ = make_director(llm)
    decision = await director.handle_turn(_turn())
    assert decision.action == "escalate"
    assert decision.reason == "safety_below_threshold"
    assert decision.draft_text == "Risky draft"


@pytest.mark.asyncio
async def test_escalate_risk_alto_with_safe_eval() -> None:
    llm = FakeLLM(
        structured_responses=[
            _comprehension(risk="alto"),
            _profile(safety=0.95),
        ],
        text_responses=["Careful draft"],
    )
    director, _, _ = make_director(llm)
    decision = await director.handle_turn(_turn())
    assert decision.action == "escalate"
    assert decision.reason == "risk_high"
    assert decision.draft_text == "Careful draft"


@pytest.mark.asyncio
async def test_tac01_llm_calls_only_analyst_generator_evaluator() -> None:
    """Control flow / Decider path must not invoke the LLM (TAC-01)."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            _profile(safety=0.8),
        ],
        text_responses=["ok draft"],
    )
    director, _, _ = make_director(llm)
    await director.handle_turn(_turn())

    methods = [name for name, _ in llm.calls]
    # Exactly: Analyst structured, Generator text, Evaluator structured
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
    ]
    assert llm.calls[0][1]["schema"].__name__ == "Comprehension"
    assert llm.calls[2][1]["schema"].__name__ == "EvaluationProfile"
    # Three total — zero extra for Planner/Decider/Director branching
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_tac04_trace_contains_all_seven_keys() -> None:
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    await director.handle_turn(turn)

    keys = trace.keys_for(turn.turn_id)
    assert keys == set(TRACE_KEYS)
    assert set(TRACE_KEYS) == {
        "comprehension",
        "plan",
        "retrieved",
        "prompt_text",
        "generated_text",
        "evaluation",
        "decision",
    }
    decision = trace.get(turn.turn_id, "decision")
    assert isinstance(decision, dict)
    assert decision["draft_text"] == "draft"
    assert decision["action"] in ("approve", "escalate")
    # JSON-ready snapshots — not live Pydantic instances
    assert not isinstance(trace.get(turn.turn_id, "comprehension"), Comprehension)
    assert isinstance(trace.get(turn.turn_id, "comprehension"), dict)


@pytest.mark.asyncio
async def test_registry_isolation_history_uses_turn_chat_id() -> None:
    history = InMemoryMessageHistory(
        {
            42: [{"role": "vip", "text": "from-42"}],
            99: [{"role": "vip", "text": "from-99"}],
        }
    )
    llm = FakeLLM(
        structured_responses=[
            _comprehension(needs_history=True, needs_context=True),
            _profile(),
        ],
        text_responses=["draft"],
    )
    director, trace, _ = make_director(llm, history_port=history)
    turn = _turn(chat_id=42)
    await director.handle_turn(turn)

    retrieved = trace.get(turn.turn_id, "retrieved")
    assert retrieved is not None
    assert "knowledge.history" in retrieved
    assert retrieved["knowledge.history"] == [{"role": "vip", "text": "from-42"}]
    # Stubs are None
    assert retrieved.get("knowledge.memory") is None or "knowledge.memory" not in (
        retrieved if isinstance(retrieved, dict) else {}
    )
    # Plan only requested history+context by default needs
    plan = trace.get(turn.turn_id, "plan")
    assert plan["capabilities"] == ["knowledge.history", "knowledge.context"]


@pytest.mark.asyncio
async def test_status_sink_receives_pipeline_transitions() -> None:
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    sink = InMemoryTurnStatusSink()
    director, _, _ = make_director(llm, status_sink=sink)
    turn = _turn()
    await director.handle_turn(turn)

    statuses = [s for _, s in sink.transitions]
    assert statuses == [
        TurnStatus.ANALYZING.value,
        TurnStatus.PLANNING.value,
        TurnStatus.RETRIEVING.value,
        TurnStatus.BUILDING_CONTEXT.value,
        TurnStatus.GENERATING.value,
        TurnStatus.EVALUATING.value,
        TurnStatus.DECIDING.value,
    ]
    assert all(tid == turn.turn_id for tid, _ in sink.transitions)


@pytest.mark.asyncio
async def test_persona_appears_in_traced_prompt() -> None:
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, trace, _ = make_director(llm, persona="PERSONA-MARKER-ABC")
    turn = _turn(text="vip-text-here")
    await director.handle_turn(turn)
    prompt = trace.get(turn.turn_id, "prompt_text")
    assert "PERSONA-MARKER-ABC" in prompt
    assert "vip-text-here" in prompt


@pytest.mark.asyncio
async def test_empty_draft_escalates() -> None:
    llm = FakeLLM(
        structured_responses=[
            _comprehension(risk="bajo"),
            _profile(safety=0.9),
        ],
        text_responses=["   "],
    )
    director, _, _ = make_director(llm)
    decision = await director.handle_turn(_turn())
    assert decision.action == "escalate"
    assert decision.reason == "empty_draft"


@pytest.mark.asyncio
async def test_pipeline_exception_marks_failed_status() -> None:
    llm = FakeLLM(
        structured_responses=[],  # Analyst fails empty queue
        text_responses=[],
    )
    sink = InMemoryTurnStatusSink()
    director, _, _ = make_director(llm, status_sink=sink)
    turn = _turn()
    with pytest.raises(RuntimeError):
        await director.handle_turn(turn)
    assert sink.transitions[-1] == (turn.turn_id, TurnStatus.FAILED.value)
