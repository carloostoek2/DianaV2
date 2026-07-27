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
    InMemoryRecentIntents,
    InMemoryTraceStore,
    InMemoryTurnStatusSink,
)
from diana.cognitive.repetition_guard import RepetitionGuard
from diana.cognitive.template_gate import TemplateGate, TemplateRule
from unittest.mock import AsyncMock, MagicMock
from diana.cognitive.registry import build_default_registry
from diana.llm.fake import FakeLLM
import random

IA_TEMPLATE = "jsjsj si y sólo vivo en tu mente 😏"
SALUDO_POOL = ["Holis 😁", "Holaa, qué tal?", "Hola amor, cómo vas?"]


def _h6_template_gate() -> TemplateGate:
    """Production-shaped rules (IA first); fixed RNG for stable pool picks."""
    deteccion_ia = TemplateRule(
        id="deteccion_ia",
        trigger_patterns=[
            "eres una ia",
            "eres un bot",
            "eres ia",
            "hablo con una ia",
            "hablo con un bot",
            "eres real",
        ],
        max_words=None,
        response_pool=[IA_TEMPLATE],
        reason="plantilla_deteccion_ia",
    )
    saludo = TemplateRule(
        id="saludo_constante",
        trigger_patterns=[
            "hola",
            "holaa",
            "holis",
            "buenas",
            "buenos días",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "hey",
            "qué tal",
            "que tal",
        ],
        max_words=4,
        response_pool=list(SALUDO_POOL),
        reason="plantilla_saludo",
    )

    return TemplateGate(rules=[deteccion_ia, saludo], rng=random.Random(0))



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
    style_rules: list[str] | None = None,
    analyst_history_limit: int = 8,
    context_builder: ContextBuilder | None = None,
    max_prompt_chars: int | None = None,
    recent_intents: InMemoryRecentIntents | None = None,
    repetition_guard: RepetitionGuard | None = None,
    template_gate: TemplateGate | None = None,
    naturalness_min: float | None = None,
) -> tuple[CognitiveDirector, InMemoryTraceStore, InMemoryMessageHistory]:
    history = history_port or InMemoryMessageHistory()
    trace = InMemoryTraceStore()
    if context_builder is None:
        if max_prompt_chars is not None:
            context_builder = ContextBuilder(max_prompt_chars=max_prompt_chars)
        else:
            context_builder = ContextBuilder()
    director_kwargs: dict = {}
    if naturalness_min is not None:
        director_kwargs["naturalness_min"] = naturalness_min
    director = CognitiveDirector(
        analyst=Analyst(fake_llm),
        planner=Planner(),
        registry=build_default_registry(history),
        context_builder=context_builder,
        generator=Generator(fake_llm),
        evaluator=Evaluator(fake_llm),
        decider=Decider(thresholds=thresholds),
        trace=trace,
        persona=persona,
        style_rules=style_rules,
        status_sink=status_sink,
        history=history,
        analyst_history_limit=analyst_history_limit,
        recent_intents=recent_intents,
        repetition_guard=repetition_guard,
        template_gate=template_gate,
        **director_kwargs,
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
    assert decision.mode_restriction_applied == "supervised_send_to_approve"


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
)


@pytest.mark.asyncio
async def test_tac04_trace_contains_all_keys_including_timings() -> None:
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    await director.handle_turn(turn)

    keys = trace.keys_for(turn.turn_id)
    assert set(TRACE_KEYS).issubset(keys)
    assert "timings" in keys
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
async def test_director_plan_omits_history_when_needs_history_false() -> None:
    """Anexo C.3 blast: plan/retrieved omit knowledge.history when needs_history is false."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(
                needs_history=False,
                needs_context=True,
                needs_memory=False,
                needs_policy=False,
                needs_examples=False,
                needs_schedule=False,
            ),
            _profile(),
        ],
        text_responses=["draft without forced history"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    decision = await director.handle_turn(turn)

    assert isinstance(decision, Decision)
    assert decision.action in ("approve", "escalate")

    plan = trace.get(turn.turn_id, "plan")
    assert isinstance(plan, dict)
    assert "knowledge.history" not in plan["capabilities"]
    assert "knowledge.context" in plan["capabilities"]
    assert plan["capabilities"] == ["knowledge.context"]

    retrieved = trace.get(turn.turn_id, "retrieved")
    assert isinstance(retrieved, dict)
    assert set(retrieved.keys()) == set(plan["capabilities"])
    assert "knowledge.history" not in retrieved

    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
    ]
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_director_empty_plan_when_all_needs_false() -> None:
    """Anexo C.3 blast: all needs_* false → empty plan/retrieved; pipeline completes."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(
                needs_history=False,
                needs_context=False,
                needs_memory=False,
                needs_policy=False,
                needs_examples=False,
                needs_schedule=False,
            ),
            _profile(),
        ],
        text_responses=["draft with empty knowledge plan"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    decision = await director.handle_turn(turn)

    assert isinstance(decision, Decision)
    assert decision.action in ("approve", "escalate")
    assert decision.draft_text == "draft with empty knowledge plan"

    plan = trace.get(turn.turn_id, "plan")
    assert isinstance(plan, dict)
    assert plan["capabilities"] == []

    retrieved = trace.get(turn.turn_id, "retrieved")
    assert isinstance(retrieved, dict)
    assert retrieved == {}
    assert set(retrieved.keys()) == set(plan["capabilities"])

    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
    ]
    assert len(llm.calls) == 3


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
    assert retrieved["knowledge.history"] == [
        {"autor": "vip", "texto": "from-42", "timestamp": ""},
    ]
    ctx = retrieved["knowledge.context"]
    assert isinstance(ctx, dict)
    assert ctx["waiting_for_reply_since"] == ""
    assert ctx["is_first_message_of_day"] is True
    assert "dia_semana" in ctx
    assert "hora_actual" in ctx
    # H9: schedule is a real seat — dict payload, never None when planned.
    schedule = retrieved["knowledge.schedule"]
    assert isinstance(schedule, dict)
    assert schedule["tipo"] in {"actividad", "respuesta_libre"}
    # Remaining planned stub caps must be present and None (not vacuous omission).
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
async def test_generator_empty_fails_before_evaluator() -> None:
    """E.4: permanent empty generation aborts before Evaluator/Decider."""
    from diana.cognitive.exceptions import GeneratorEmptyOutputError
    from diana.cognitive.models import EvaluationProfile

    llm = FakeLLM(
        structured_responses=[
            _comprehension(risk="bajo"),
            # Evaluator profile must never be consumed on gen fail.
            _profile(safety=0.9),
        ],
        text_responses=["", "  "],
    )
    sink = InMemoryTurnStatusSink()
    director, trace, _ = make_director(llm, status_sink=sink)
    turn = _turn()
    with pytest.raises(GeneratorEmptyOutputError) as ei:
        await director.handle_turn(turn)
    assert str(ei.value) == "generador_salida_vacia"
    assert ei.value.reason == "generador_salida_vacia"

    keys = trace.keys_for(turn.turn_id)
    assert "generated_text" not in keys
    assert "evaluation" not in keys
    assert "decision" not in keys

    statuses = [s for _, s in sink.transitions]
    assert TurnStatus.GENERATING.value in statuses
    assert TurnStatus.EVALUATING.value not in statuses
    assert TurnStatus.DECIDING.value not in statuses
    assert statuses[-1] == TurnStatus.FAILED.value

    # Only Analyst structured call — no EvaluationProfile structured call.
    structured = [c for c in llm.calls if c[0] == "generate_structured"]
    assert len(structured) == 1
    assert structured[0][1]["schema"] is not EvaluationProfile
    generate_calls = [c for c in llm.calls if c[0] == "generate"]
    assert len(generate_calls) == 2


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
async def test_director_prompt_uses_built_context_current_turn_last() -> None:
    """Trace prompt_text is a string with Current VIP message after knowledge/comprehension."""
    history = InMemoryMessageHistory(
        {42: [{"role": "vip", "text": "prior-hist-line", "telegram_message_id": 1}]}
    )
    llm = FakeLLM(
        structured_responses=[
            _comprehension(needs_history=True, needs_context=True),
            _profile(),
        ],
        text_responses=["draft"],
    )
    director, trace, _ = make_director(llm, history_port=history)
    turn = _turn(chat_id=42, text="CURRENT-TURN-BODY")
    await director.handle_turn(turn)

    prompt = trace.get(turn.turn_id, "prompt_text")
    assert isinstance(prompt, str)
    headings = [line for line in prompt.splitlines() if line.startswith("## ")]
    assert headings[0] == "## Persona"
    assert headings[-1] == "## Current VIP message"
    assert "## Comprehension" in headings
    assert prompt.index("## Comprehension") < prompt.index("## Current VIP message")
    assert "CURRENT-TURN-BODY" in prompt


@pytest.mark.asyncio
async def test_director_context_exceeds_limit_no_decision() -> None:
    """Size fail aborts before Decision; typed error; no Generator text call."""
    from diana.cognitive.exceptions import ContextExceedsLimitError

    history = InMemoryMessageHistory(
        {
            42: [
                {
                    "role": "vip",
                    "text": "HUGE-HISTORY-" + ("X" * 500),
                    "telegram_message_id": 1,
                }
            ]
        }
    )
    llm = FakeLLM(
        structured_responses=[
            _comprehension(needs_history=True, needs_context=True),
        ],
        text_responses=["should-not-be-used"],
    )
    sink = InMemoryTurnStatusSink()
    director, trace, _ = make_director(
        llm,
        history_port=history,
        status_sink=sink,
        max_prompt_chars=80,
    )
    turn = _turn(chat_id=42, text="now")
    with pytest.raises(ContextExceedsLimitError) as ei:
        await director.handle_turn(turn)
    assert str(ei.value) == "contexto_excede_limite"
    assert ei.value.reason == "contexto_excede_limite"
    keys = trace.keys_for(turn.turn_id)
    assert "decision" not in keys
    assert "generated_text" not in keys
    # Store happens only after successful build — no prompt_text on fail.
    assert "prompt_text" not in keys
    # Generator uses generate (text); size fail must not call it.
    assert not any(c[0] == "generate" for c in llm.calls)
    statuses = [s for _, s in sink.transitions]
    assert TurnStatus.BUILDING_CONTEXT.value in statuses
    assert TurnStatus.GENERATING.value not in statuses
    assert statuses[-1] == TurnStatus.FAILED.value


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



@pytest.mark.asyncio
async def test_style_rules_reach_prompt_text() -> None:
    """J.1: Director passes style_rules into ContextBuilder persona section."""
    distinctive = "Preguntas: solo cierre '?', nunca abre con '¿'. Regla inquebrantable."
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["draft"],
    )
    director, trace, _ = make_director(
        llm,
        persona="Eres Diana, 27 años.",
        style_rules=[distinctive, "Máximo 2-3 líneas por mensaje."],
    )
    turn = _turn(text="vip-style-check")
    await director.handle_turn(turn)
    prompt = trace.get(turn.turn_id, "prompt_text")
    assert isinstance(prompt, str)
    assert "Eres Diana, 27 años." in prompt
    assert distinctive in prompt
    assert "Máximo 2-3 líneas por mensaje." in prompt
    assert "vip-style-check" in prompt

# ── H4 pregunta_repetida early-exit ───────────────────────────────────


@pytest.mark.asyncio
async def test_repetition_early_exit_skips_generator_evaluator_planner() -> None:
    """3× same intent → escalate pregunta_repetida; Planner/Gen/Eval not called."""
    intents = InMemoryRecentIntents()
    intents.seed(42, ["precio", "precio"])  # 2 prior; current makes streak 3
    llm = FakeLLM(
        structured_responses=[
            _comprehension(intent="precio", risk="bajo"),
            # Evaluator must NOT be called; if it is, structured queue empties
            _profile(safety=0.9),
        ],
        text_responses=["should-not-generate"],
    )
    director, trace, _ = make_director(
        llm,
        recent_intents=intents,
        repetition_guard=RepetitionGuard(threshold=3),
    )
    # Spy collaborators after construction
    director._planner.plan = MagicMock(side_effect=director._planner.plan)  # type: ignore[method-assign]
    director._generator.generate = AsyncMock(side_effect=director._generator.generate)  # type: ignore[method-assign]
    director._evaluator.evaluate = AsyncMock(side_effect=director._evaluator.evaluate)  # type: ignore[method-assign]

    turn = _turn(chat_id=42, text="otra vez el precio")
    decision = await director.handle_turn(turn)

    assert decision.action == "escalate"
    assert decision.reason == "pregunta_repetida"
    assert decision.draft_text is None
    assert trace.get(turn.turn_id, "comprehension") is not None
    assert trace.get(turn.turn_id, "decision") is not None
    assert trace.get(turn.turn_id, "plan") is None
    assert trace.get(turn.turn_id, "generated_text") is None
    director._planner.plan.assert_not_called()  # type: ignore[attr-defined]
    director._generator.generate.assert_not_called()  # type: ignore[attr-defined]
    director._evaluator.evaluate.assert_not_called()  # type: ignore[attr-defined]
    # Analyst only: one structured call
    methods = [name for name, _ in llm.calls]
    assert methods == ["generate_structured"]


@pytest.mark.asyncio
async def test_repetition_not_triggered_with_two_total() -> None:
    """1 prior same intent → full pipeline continues (approve path)."""
    intents = InMemoryRecentIntents()
    intents.seed(42, ["precio"])  # streak would be 2 < 3
    llm = FakeLLM(
        structured_responses=[
            _comprehension(intent="precio", risk="bajo"),
            _profile(safety=0.9),
        ],
        text_responses=["Full path draft"],
    )
    director, trace, _ = make_director(
        llm,
        recent_intents=intents,
        repetition_guard=RepetitionGuard(threshold=3),
    )
    turn = _turn(chat_id=42, text="precio de nuevo")
    decision = await director.handle_turn(turn)

    assert decision.action == "approve"
    assert decision.draft_text == "Full path draft"
    assert trace.get(turn.turn_id, "plan") is not None
    assert trace.get(turn.turn_id, "generated_text") == "Full path draft"
    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
    ]

@pytest.mark.asyncio
async def test_director_timings_include_persona_and_voice_buckets() -> None:
    """Retriever timing map always sets persona_facts_ms and voice_patterns_ms."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(
                needs_history=False,
                needs_context=False,
                needs_persona_facts=True,
                needs_voice_patterns=True,
            ),
            _profile(),
        ],
        text_responses=["draft"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    await director.handle_turn(turn)

    timings = trace.get(turn.turn_id, "timings")
    assert isinstance(timings, dict)
    assert "persona_facts_ms" in timings
    assert "voice_patterns_ms" in timings
    assert timings["persona_facts_ms"] >= 0.0
    assert timings["voice_patterns_ms"] >= 0.0
    # Capabilities planned should include both knowledge keys when needs_* true.
    plan = trace.get(turn.turn_id, "plan")
    assert "knowledge.persona_facts" in plan["capabilities"]
    assert "knowledge.voice_patterns" in plan["capabilities"]
    # Existing buckets still present when any retriever ran.
    assert "memory_retriever_ms" in timings
    assert "policy_retriever_ms" in timings
    assert "examples_retriever_ms" in timings


# --- Naturalness 1× redraft (Director pre-Decider MVP) ---


@pytest.mark.asyncio
async def test_naturalness_above_min_no_redraft() -> None:
    """High naturalness: TAC-01 three LLM calls; draft unchanged; no redraft."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            _profile(naturalness=0.9),
        ],
        text_responses=["draft-a"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    decision = await director.handle_turn(turn)

    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
    ]
    assert len(llm.calls) == 3
    assert decision.draft_text == "draft-a"
    assert decision.action == "approve"
    timings = trace.get(turn.turn_id, "timings")
    assert isinstance(timings, dict)
    assert "naturalness_redraft" not in timings


@pytest.mark.asyncio
async def test_naturalness_below_min_redrafts_once() -> None:
    """Low naturalness → exactly one extra G+E; final draft/eval from second attempt."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            _profile(naturalness=0.2),
            _profile(naturalness=0.9),
        ],
        text_responses=["draft-low", "draft-high"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    decision = await director.handle_turn(turn)

    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
        "generate",
        "generate_structured",
    ]
    assert len(llm.calls) == 5
    assert decision.draft_text == "draft-high"
    assert decision.evaluation.naturalness == 0.9
    assert decision.action == "approve"

    assert trace.get(turn.turn_id, "generated_text") == "draft-high"
    evaluation = trace.get(turn.turn_id, "evaluation")
    assert isinstance(evaluation, dict)
    assert evaluation["naturalness"] == 0.9
    # Exactly one decision store (Decider once).
    decision_payload = trace.get(turn.turn_id, "decision")
    assert isinstance(decision_payload, dict)
    assert decision_payload["draft_text"] == "draft-high"

    generate_calls = [c for c in llm.calls if c[0] == "generate"]
    assert len(generate_calls) == 2
    # Same prompt_final on both generates (byte-identical user content).
    assert generate_calls[0][1]["messages"] == generate_calls[1][1]["messages"]

    timings = trace.get(turn.turn_id, "timings")
    assert isinstance(timings, dict)
    assert timings.get("naturalness_redraft") == 1.0
    # Audit flag must not inflate total_ms (sum only *_ms duration keys).
    ms_sum = sum(
        v for k, v in timings.items() if k.endswith("_ms") and k != "total_ms"
    )
    assert timings["total_ms"] == pytest.approx(ms_sum)
    assert "generator_redraft_ms" in timings
    assert "evaluator_redraft_ms" in timings


@pytest.mark.asyncio
async def test_naturalness_equal_min_no_redraft() -> None:
    """Boundary: naturalness == min (0.5) does not redraft."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            _profile(naturalness=0.5),
        ],
        text_responses=["draft-boundary"],
    )
    director, _, _ = make_director(llm)
    decision = await director.handle_turn(_turn())

    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
    ]
    assert len(llm.calls) == 3
    assert decision.draft_text == "draft-boundary"


@pytest.mark.asyncio
async def test_naturalness_redraft_never_third_generate() -> None:
    """Second naturalness still low → no third generate; decide on second draft."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            _profile(naturalness=0.1),
            _profile(naturalness=0.1),
        ],
        text_responses=["a", "b"],
    )
    director, _, _ = make_director(llm)
    decision = await director.handle_turn(_turn())

    generate_calls = [c for c in llm.calls if c[0] == "generate"]
    assert len(generate_calls) == 2
    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
        "generate",
        "generate_structured",
    ]
    assert decision.draft_text == "b"
    assert decision.evaluation.naturalness == 0.1
    assert decision.action == "approve"


@pytest.mark.asyncio
async def test_naturalness_redraft_then_decide_once() -> None:
    """After redraft, Decider runs once; single decision payload in trace."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            _profile(naturalness=0.1),
            _profile(naturalness=0.95, safety=0.95),
        ],
        text_responses=["stiff", "natural"],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    decision = await director.handle_turn(turn)

    assert decision.action == "approve"
    assert decision.reason == "ok_for_human_review"
    assert decision.draft_text == "natural"
    keys = trace.keys_for(turn.turn_id)
    assert "decision" in keys
    # Overwrite semantics: one decision key, final payload only.
    payload = trace.get(turn.turn_id, "decision")
    assert isinstance(payload, dict)
    assert payload["action"] == "approve"
    assert payload["draft_text"] == "natural"


@pytest.mark.asyncio
async def test_naturalness_second_generate_empty_fail_closed() -> None:
    """Second generate permanently empty → GeneratorEmptyOutputError; no decision."""
    from diana.cognitive.exceptions import GeneratorEmptyOutputError

    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            _profile(naturalness=0.2),
            # Second eval must never be consumed.
            _profile(naturalness=0.9),
        ],
        # First G ok; second G: empty + retry empty → GeneratorEmptyOutputError.
        text_responses=["draft-low", "", "  "],
    )
    director, trace, _ = make_director(llm)
    turn = _turn()
    with pytest.raises(GeneratorEmptyOutputError) as ei:
        await director.handle_turn(turn)
    assert ei.value.reason == "generador_salida_vacia"

    keys = trace.keys_for(turn.turn_id)
    assert "decision" not in keys
    # First draft/eval may remain (overwrite of draft not completed on empty fail).
    assert "evaluation" in keys
    generate_calls = [c for c in llm.calls if c[0] == "generate"]
    # 1 success + 2 empty attempts on redraft
    assert len(generate_calls) == 3


@pytest.mark.asyncio
async def test_naturalness_custom_min_via_ctor() -> None:
    """Ctor naturalness_min overrides default 0.5 supervised constant."""
    llm = FakeLLM(
        structured_responses=[
            _comprehension(),
            _profile(naturalness=0.55),
            _profile(naturalness=0.9),
        ],
        text_responses=["mid", "better"],
    )
    director, _, _ = make_director(llm, naturalness_min=0.6)
    decision = await director.handle_turn(_turn())

    methods = [name for name, _ in llm.calls]
    assert methods == [
        "generate_structured",
        "generate",
        "generate_structured",
        "generate",
        "generate_structured",
    ]
    assert len(llm.calls) == 5
    assert decision.draft_text == "better"


# ── H6 TemplateGate pre-pipeline early-exit ────────────────────────────


def _assert_zero_evaluation(evaluation: EvaluationProfile) -> None:
    assert evaluation.naturalness == 0.0
    assert evaluation.precision == 0.0
    assert evaluation.doctrine == 0.0
    assert evaluation.consistency == 0.0
    assert evaluation.safety == 0.0
    assert evaluation.coverage == 0.0
    assert evaluation.empathy == 0.0


@pytest.mark.asyncio
async def test_h6_short_hola_template_approve_skips_pipeline() -> None:
    """H6.6.1: short greeting → plantilla_saludo approve; 0 LLM; decision+generated_text."""
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["should-not-run"],
    )
    director, trace, _ = make_director(llm, template_gate=_h6_template_gate())
    director._analyst.analyze = AsyncMock(side_effect=director._analyst.analyze)  # type: ignore[method-assign]
    director._planner.plan = MagicMock(side_effect=director._planner.plan)  # type: ignore[method-assign]
    director._generator.generate = AsyncMock(side_effect=director._generator.generate)  # type: ignore[method-assign]
    director._evaluator.evaluate = AsyncMock(side_effect=director._evaluator.evaluate)  # type: ignore[method-assign]
    director._decider.decide = MagicMock(side_effect=director._decider.decide)  # type: ignore[method-assign]

    turn = _turn(text="Hola")
    decision = await director.handle_turn(turn)

    assert decision.action == "approve"
    assert decision.reason == "plantilla_saludo"
    assert decision.draft_text in SALUDO_POOL
    assert decision.draft_text
    _assert_zero_evaluation(decision.evaluation)
    assert decision.mode_restriction_applied is None

    assert trace.get(turn.turn_id, "decision") is not None
    assert trace.get(turn.turn_id, "generated_text") == decision.draft_text
    assert trace.get(turn.turn_id, "comprehension") is None
    assert trace.get(turn.turn_id, "plan") is None
    assert trace.get(turn.turn_id, "evaluation") is None

    director._analyst.analyze.assert_not_called()  # type: ignore[attr-defined]
    director._planner.plan.assert_not_called()  # type: ignore[attr-defined]
    director._generator.generate.assert_not_called()  # type: ignore[attr-defined]
    director._evaluator.evaluate.assert_not_called()  # type: ignore[attr-defined]
    director._decider.decide.assert_not_called()  # type: ignore[attr-defined]
    assert llm.calls == []


@pytest.mark.asyncio
async def test_h6_long_hola_does_not_template_runs_pipeline() -> None:
    """H6.6.2: long hola message skips template; full pipeline still runs."""
    llm = FakeLLM(
        structured_responses=[_comprehension(risk="medio"), _profile(safety=0.5)],
        text_responses=["Long path draft"],
    )
    director, trace, _ = make_director(llm, template_gate=_h6_template_gate())
    long_text = "Hola, tengo una pregunta sobre el contenido"
    turn = _turn(text=long_text)
    decision = await director.handle_turn(turn)

    assert decision.action == "approve"
    assert decision.reason != "plantilla_saludo"
    assert decision.draft_text == "Long path draft"
    assert trace.get(turn.turn_id, "comprehension") is not None
    assert trace.get(turn.turn_id, "plan") is not None
    methods = [name for name, _ in llm.calls]
    assert "generate_structured" in methods
    assert "generate" in methods


@pytest.mark.asyncio
async def test_h6_ia_probe_template_exact_draft() -> None:
    """H6.6.3: IA probe → exact template draft + plantilla_deteccion_ia; 0 pipeline."""
    llm = FakeLLM(
        structured_responses=[_comprehension(), _profile()],
        text_responses=["should-not-run"],
    )
    director, trace, _ = make_director(llm, template_gate=_h6_template_gate())
    director._analyst.analyze = AsyncMock(side_effect=director._analyst.analyze)  # type: ignore[method-assign]
    director._planner.plan = MagicMock(side_effect=director._planner.plan)  # type: ignore[method-assign]
    director._generator.generate = AsyncMock(side_effect=director._generator.generate)  # type: ignore[method-assign]
    director._evaluator.evaluate = AsyncMock(side_effect=director._evaluator.evaluate)  # type: ignore[method-assign]
    director._decider.decide = MagicMock(side_effect=director._decider.decide)  # type: ignore[method-assign]

    turn = _turn(text="eres una ia?")
    decision = await director.handle_turn(turn)

    assert decision.action == "approve"
    assert decision.reason == "plantilla_deteccion_ia"
    assert decision.draft_text == IA_TEMPLATE
    _assert_zero_evaluation(decision.evaluation)
    assert llm.calls == []
    assert trace.get(turn.turn_id, "decision") is not None
    assert trace.get(turn.turn_id, "generated_text") == IA_TEMPLATE
    assert trace.get(turn.turn_id, "comprehension") is None
    director._analyst.analyze.assert_not_called()  # type: ignore[attr-defined]
    director._planner.plan.assert_not_called()  # type: ignore[attr-defined]
    director._generator.generate.assert_not_called()  # type: ignore[attr-defined]
    director._evaluator.evaluate.assert_not_called()  # type: ignore[attr-defined]
    director._decider.decide.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_h6_template_decision_never_send_or_escalate() -> None:
    """H6.6.4: template Decision is supervised approve only (no send/escalate)."""
    llm = FakeLLM(structured_responses=[], text_responses=[])
    director, _, _ = make_director(llm, template_gate=_h6_template_gate())

    for text in ("Hola", "eres una ia?", "hola eres una ia"):
        decision = await director.handle_turn(_turn(text=text))
        assert decision.action == "approve"
        assert decision.action not in ("send", "escalate")
        assert decision.draft_text
        assert decision.evaluation is not None
        _assert_zero_evaluation(decision.evaluation)
    mixed = await director.handle_turn(_turn(text="hola eres una ia"))
    assert mixed.reason == "plantilla_deteccion_ia"
    assert llm.calls == []



@pytest.mark.asyncio
async def test_h6_default_gate_none_does_not_false_fire_hola_diana() -> None:
    """Default template_gate=None keeps fixture text 'hola Diana' on full pipeline."""
    llm = FakeLLM(
        structured_responses=[_comprehension(risk="medio"), _profile(safety=0.5)],
        text_responses=["Fixture path draft"],
    )
    director, _, _ = make_director(llm)  # no template_gate
    decision = await director.handle_turn(_turn(text="hola Diana"))
    assert decision.draft_text == "Fixture path draft"
    assert decision.reason != "plantilla_saludo"
    assert any(name == "generate" for name, _ in llm.calls)


