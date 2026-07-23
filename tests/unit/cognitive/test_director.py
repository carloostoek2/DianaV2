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
    analyst_history_limit: int = 8,
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
        history=history,
        analyst_history_limit=analyst_history_limit,
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


_EVAL_DIMS = (
    "naturalness",
    "precision",
    "doctrine",
    "consistency",
    "safety",
    "coverage",
    "empathy",
)

_STUB_CAPS = (
    "knowledge.memory",
    "knowledge.policy",
    "knowledge.examples",
    "knowledge.schedule",
)


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

    comprehension = trace.get(turn.turn_id, "comprehension")
    assert not isinstance(comprehension, Comprehension)
    assert isinstance(comprehension, dict)
    assert comprehension["intent"] == "chat"
    assert comprehension["risk"] in ("bajo", "medio", "alto")

    plan = trace.get(turn.turn_id, "plan")
    assert isinstance(plan, dict)
    assert isinstance(plan["capabilities"], list)
    assert plan["capabilities"] == ["knowledge.history", "knowledge.context"]

    retrieved = trace.get(turn.turn_id, "retrieved")
    assert isinstance(retrieved, dict)
    assert set(retrieved.keys()) == set(plan["capabilities"])

    prompt_text = trace.get(turn.turn_id, "prompt_text")
    assert isinstance(prompt_text, str)
    assert prompt_text.strip()
    assert "hola Diana" in prompt_text

    generated_text = trace.get(turn.turn_id, "generated_text")
    assert isinstance(generated_text, str)
    assert generated_text == "draft"

    evaluation = trace.get(turn.turn_id, "evaluation")
    assert isinstance(evaluation, dict)
    for dim in _EVAL_DIMS:
        assert dim in evaluation
        assert isinstance(evaluation[dim], (int, float))
        assert 0.0 <= float(evaluation[dim]) <= 1.0

    decision = trace.get(turn.turn_id, "decision")
    assert isinstance(decision, dict)
    assert decision["draft_text"] == "draft"
    assert decision["action"] in ("approve", "escalate")
    assert decision["reason"]
    assert isinstance(decision["evaluation"], dict)


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
            _comprehension(
                needs_history=True,
                needs_context=True,
                needs_memory=True,
                needs_policy=True,
                needs_examples=True,
                needs_schedule=True,
            ),
            _profile(),
        ],
        text_responses=["draft"],
    )
    director, trace, _ = make_director(llm, history_port=history)
    turn = _turn(chat_id=42)
    await director.handle_turn(turn)

    retrieved = trace.get(turn.turn_id, "retrieved")
    assert isinstance(retrieved, dict)
    assert retrieved["knowledge.history"] == [{"role": "vip", "text": "from-42"}]
    assert isinstance(retrieved["knowledge.context"], dict)
    assert retrieved["knowledge.context"]["message_count"] == 1
    # All planned stub caps must be present and None (not vacuous omission).
    for cap in _STUB_CAPS:
        assert cap in retrieved
        assert retrieved[cap] is None
    plan = trace.get(turn.turn_id, "plan")
    assert plan["capabilities"] == [
        "knowledge.history",
        "knowledge.context",
        "knowledge.memory",
        "knowledge.policy",
        "knowledge.examples",
        "knowledge.schedule",
    ]


def test_director_source_has_no_llm_control_flow() -> None:
    """TAC-01 defense-in-depth: Director must not call structured LLM or import llm."""
    import ast
    import inspect

    from diana.cognitive import director as director_mod

    source = inspect.getsource(director_mod)
    assert "generate_structured" not in source
    assert "LLMProvider" not in source
    assert "diana.llm" not in source
    assert "mean(" not in source
    assert "overall_score" not in source

    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(
        mod == "diana.llm" or mod.startswith("diana.llm.") for mod in imported
    )


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


@pytest.mark.asyncio
async def test_director_passes_historial_to_analyst() -> None:
    history = InMemoryMessageHistory(
        {
            42: [
                {
                    "role": "vip",
                    "text": "hist-vip-XYZ",
                    "timestamp": "2026-01-01T10:00:00Z",
                    "telegram_message_id": 1,
                },
                {
                    "role": "owner",
                    "text": "hist-owner-UVW",
                    "timestamp": "2026-01-01T10:01:00Z",
                    "telegram_message_id": 2,
                },
                {
                    "role": "bot",
                    "text": "hist-bot-SHOULD-ABSENT",
                    "timestamp": "2026-01-01T10:02:00Z",
                    "telegram_message_id": 3,
                },
            ]
        }
    )
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, _, _ = make_director(llm, history_port=history)
    await director.handle_turn(_turn(chat_id=42, text="current-msg"))

    analyst_messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in analyst_messages)
    assert "hist-vip-XYZ" in flat
    assert "hist-owner-UVW" in flat
    assert "dueña" in flat  # owner → dueña mapping
    assert "hist-bot-SHOULD-ABSENT" not in flat
    assert "current-msg" in flat


@pytest.mark.asyncio
async def test_director_analyst_history_respects_limit_8() -> None:
    """Default analyst_history_limit=8: only the last 8 human (vip/dueña) lines."""
    older = [
        {
            "role": "vip",
            "text": f"hist-old-{i:02d}-SHOULD-ABSENT",
            "timestamp": f"2026-01-01T09:{i:02d}:00Z",
        }
        for i in range(5)
    ]
    window = [
        {
            "role": "vip",
            "text": f"hist-win-{i:02d}-KEEP",
            "timestamp": f"2026-01-01T10:{i:02d}:00Z",
        }
        for i in range(8)
    ]
    history = InMemoryMessageHistory({42: older + window})
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, _, _ = make_director(llm, history_port=history, analyst_history_limit=8)
    await director.handle_turn(_turn(chat_id=42, text="current-msg"))

    analyst_messages = llm.calls[0][1]["messages"]
    flat = " ".join(m.get("content", "") for m in analyst_messages)
    for i in range(5):
        assert f"hist-old-{i:02d}-SHOULD-ABSENT" not in flat
    for i in range(8):
        assert f"hist-win-{i:02d}-KEEP" in flat


@pytest.mark.asyncio
async def test_director_excludes_current_vip_message_from_historial() -> None:
    """Current turn must not appear twice (turno_actual + historial tail)."""
    history = InMemoryMessageHistory(
        {
            42: [
                {
                    "role": "vip",
                    "text": "older-vip",
                    "timestamp": "2026-01-01T10:00:00Z",
                    "telegram_message_id": 10,
                },
                {
                    "role": "vip",
                    "text": "current-msg",
                    "timestamp": "2026-01-01T10:05:00Z",
                    "telegram_message_id": 99,
                },
            ]
        }
    )
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, _, _ = make_director(llm, history_port=history)
    turn = IncomingTurn(
        turn_id=uuid4(),
        chat_id=42,
        text="current-msg",
        telegram_message_id=99,
    )
    await director.handle_turn(turn)

    analyst_messages = llm.calls[0][1]["messages"]
    user = next(m["content"] for m in analyst_messages if m.get("role") == "user")
    assert "turno_actual:\ncurrent-msg" in user
    # Only one occurrence of current-msg overall (turno_actual), not also in history.
    assert user.count("current-msg") == 1
    assert "older-vip" in user


@pytest.mark.asyncio
async def test_director_excludes_trailing_vip_text_when_message_id_missing() -> None:
    history = InMemoryMessageHistory(
        {
            42: [
                {"role": "vip", "text": "prior", "timestamp": "t1"},
                {"role": "vip", "text": "dup-current", "timestamp": "t2"},
            ]
        }
    )
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, _, _ = make_director(llm, history_port=history)
    await director.handle_turn(_turn(chat_id=42, text="dup-current"))
    user = next(
        m["content"] for m in llm.calls[0][1]["messages"] if m.get("role") == "user"
    )
    assert user.count("dup-current") == 1
    assert "prior" in user


@pytest.mark.asyncio
async def test_director_filters_bot_before_applying_human_limit() -> None:
    """Oversample + filter: bot-heavy tail still fills limit with vip/owner lines."""
    rows: list[dict] = []
    # Older VIP lines that must survive after bot filter + limit=3
    for i in range(3):
        rows.append(
            {
                "role": "vip",
                "text": f"keep-human-{i}",
                "timestamp": f"2026-01-01T08:{i:02d}:00Z",
            }
        )
    # Interleaved bots that would starve a raw limit=3 window
    for i in range(10):
        rows.append(
            {
                "role": "bot",
                "text": f"bot-noise-{i}",
                "timestamp": f"2026-01-01T09:{i:02d}:00Z",
            }
        )
    rows.append(
        {
            "role": "owner",
            "text": "keep-owner",
            "timestamp": "2026-01-01T10:00:00Z",
        }
    )
    history = InMemoryMessageHistory({42: rows})
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, _, _ = make_director(llm, history_port=history, analyst_history_limit=3)
    await director.handle_turn(_turn(chat_id=42, text="now"))
    flat = " ".join(m.get("content", "") for m in llm.calls[0][1]["messages"])
    assert "bot-noise" not in flat
    # Last 3 human lines: keep-human-1, keep-human-2, keep-owner (or similar tail)
    assert "keep-owner" in flat
    assert "keep-human-2" in flat
    assert "keep-human-1" in flat
    assert "keep-human-0" not in flat  # trimmed by human limit=3


@pytest.mark.asyncio
async def test_director_historial_excludes_unknown_roles_and_other_chats() -> None:
    history = InMemoryMessageHistory(
        {
            42: [
                {"role": "vip", "text": "from-42", "timestamp": "t1"},
                {"role": "owner", "text": "owner-42", "timestamp": "t2"},
                {"role": "bot", "text": "bot-42", "timestamp": "t3"},
                {"role": "system", "text": "system-42-ABSENT", "timestamp": "t4"},
                {"role": "assistant", "text": "assistant-42-ABSENT", "timestamp": "t5"},
            ],
            99: [
                {"role": "vip", "text": "from-99-ABSENT", "timestamp": "t9"},
            ],
        }
    )
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, _, _ = make_director(llm, history_port=history)
    await director.handle_turn(_turn(chat_id=42, text="now"))
    flat = " ".join(m.get("content", "") for m in llm.calls[0][1]["messages"])
    assert "from-42" in flat
    assert "owner-42" in flat
    assert "dueña" in flat
    assert "bot-42" not in flat
    assert "system-42-ABSENT" not in flat
    assert "assistant-42-ABSENT" not in flat
    assert "from-99-ABSENT" not in flat


def test_map_history_messages_edge_coercion() -> None:
    mapped = CognitiveDirector._map_history_messages(
        [
            {"role": "vip", "text": None, "timestamp": None},
            {"role": None, "text": "skip", "timestamp": "t"},
            {"role": "owner", "text": "ok", "timestamp": 12345},
            "not-a-dict",  # type: ignore[list-item]
        ]
    )
    assert len(mapped) == 2
    assert mapped[0].autor == "vip"
    assert mapped[0].texto == ""
    assert mapped[0].timestamp == ""
    assert mapped[1].autor == "dueña"
    assert mapped[1].texto == "ok"
    assert mapped[1].timestamp == "12345"


@pytest.mark.asyncio
async def test_director_analyst_schema_fail_no_plan_trace() -> None:
    from diana.cognitive.exceptions import AnalystSchemaInvalidError

    invalid = {"intent": "only"}
    llm = FakeLLM(structured_responses=[invalid, invalid], text_responses=[])
    sink = InMemoryTurnStatusSink()
    director, trace, _ = make_director(llm, status_sink=sink)
    turn = _turn()
    with pytest.raises(AnalystSchemaInvalidError) as exc_info:
        await director.handle_turn(turn)
    assert str(exc_info.value) == "analista_schema_invalido"
    assert "plan" not in trace.keys_for(turn.turn_id)
    assert "comprehension" not in trace.keys_for(turn.turn_id)
    statuses = [s for _, s in sink.transitions]
    assert TurnStatus.ANALYZING.value in statuses
    assert TurnStatus.PLANNING.value not in statuses
    assert statuses[-1] == TurnStatus.FAILED.value


@pytest.mark.asyncio
async def test_director_passes_included_blocks_to_evaluator() -> None:
    """Included capability names from non-null knowledge appear in Evaluator messages."""
    history = InMemoryMessageHistory(
        {42: [{"role": "vip", "text": "prior-from-42-HISTORY-BODY"}]}
    )
    llm = FakeLLM(
        structured_responses=[
            _comprehension(needs_history=True, needs_context=True),
            _profile(),
        ],
        text_responses=["draft for vip"],
    )
    director, _, _ = make_director(llm, history_port=history)
    await director.handle_turn(_turn(chat_id=42, text="hola Diana"))

    # Evaluator is the second generate_structured call (after Analyst).
    eval_call = llm.calls[2]
    assert eval_call[0] == "generate_structured"
    assert eval_call[1]["schema"].__name__ == "EvaluationProfile"
    flat = " ".join(m.get("content", "") for m in eval_call[1]["messages"])
    assert "knowledge.history" in flat
    assert "knowledge.context" in flat
    # Anti-contamination: raw history body must not be dumped into Evaluator prompt.
    assert "prior-from-42-HISTORY-BODY" not in flat
    # Policy still null in F1 stubs — no accidental policy body dump.
    assert "SECRET-POLICY-BODY" not in flat


@pytest.mark.asyncio
async def test_director_evaluator_schema_fail_no_decision_trace() -> None:
    from diana.cognitive.exceptions import EvaluatorSchemaInvalidError

    incomplete = {d: 0.5 for d in _EVAL_DIMS if d != "empathy"}
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            incomplete,
            incomplete,
        ],
        text_responses=["draft text"],
    )
    sink = InMemoryTurnStatusSink()
    director, trace, _ = make_director(llm, status_sink=sink)
    turn = _turn()
    with pytest.raises(EvaluatorSchemaInvalidError) as ei:
        await director.handle_turn(turn)
    assert str(ei.value) == "evaluador_schema_invalido"
    keys = trace.keys_for(turn.turn_id)
    assert "decision" not in keys
    assert "evaluation" not in keys
    assert "generated_text" in keys
    statuses = [s for _, s in sink.transitions]
    assert TurnStatus.EVALUATING.value in statuses
    assert TurnStatus.DECIDING.value not in statuses
    assert statuses[-1] == TurnStatus.FAILED.value
