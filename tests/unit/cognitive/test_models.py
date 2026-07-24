"""Unit tests for F1 cognitive domain models."""

from __future__ import annotations

from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError


def _profile(**overrides: float):
    from diana.cognitive.models import EvaluationProfile

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


_CANONICAL_DIMS = (
    "naturalness",
    "precision",
    "doctrine",
    "consistency",
    "safety",
    "coverage",
    "empathy",
)


@pytest.mark.parametrize("missing_dim", _CANONICAL_DIMS)
def test_evaluation_profile_requires_all_seven_dims(missing_dim: str) -> None:
    """Missing any of the 7 canonical dimensions must fail validation."""
    from diana.cognitive.models import EvaluationProfile

    data = {dim: 0.8 for dim in _CANONICAL_DIMS}
    del data[missing_dim]
    with pytest.raises(ValidationError):
        EvaluationProfile(**data)


def test_evaluation_profile_constructs_with_seven_dims() -> None:
    profile = _profile()
    assert profile.naturalness == 0.9
    assert profile.empathy == 0.8
    assert profile.raw_llm_output is None


def test_decision_approve_and_escalate_ok() -> None:
    from diana.cognitive.models import Decision

    profile = _profile()
    approve = Decision(action="approve", reason="ok", evaluation=profile)
    escalate = Decision(
        action="escalate",
        reason="safety",
        evaluation=profile,
        draft_text="maybe",
    )
    assert approve.action == "approve"
    assert escalate.action == "escalate"
    assert escalate.draft_text == "maybe"


def test_decision_action_literal_is_exactly_approve_escalate() -> None:
    from diana.cognitive.models import Decision

    assert get_args(Decision.model_fields["action"].annotation) == ("approve", "escalate")


def test_decision_requires_evaluation() -> None:
    from diana.cognitive.models import Decision

    with pytest.raises(ValidationError):
        Decision(action="approve", reason="ok")  # type: ignore[call-arg]


def test_decision_requires_action_and_reason() -> None:
    from diana.cognitive.models import Decision

    profile = _profile()
    with pytest.raises(ValidationError):
        Decision(reason="ok", evaluation=profile)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Decision(action="approve", evaluation=profile)  # type: ignore[call-arg]

    for name in ("action", "reason", "evaluation"):
        assert Decision.model_fields[name].is_required() is True


@pytest.mark.parametrize("bad_action", ["send", "regenerate", "consult_doctrine", "wait"])
def test_decision_rejects_non_f1_actions(bad_action: str) -> None:
    from diana.cognitive.models import Decision

    with pytest.raises(ValidationError):
        Decision(action=bad_action, reason="nope", evaluation=_profile())


def test_decision_rejects_extra_score_on_nested_evaluation() -> None:
    from diana.cognitive.models import Decision

    with pytest.raises(ValidationError):
        Decision.model_validate(
            {
                "action": "approve",
                "reason": "ok",
                "evaluation": {
                    "naturalness": 0.9,
                    "precision": 0.8,
                    "doctrine": 0.85,
                    "consistency": 0.9,
                    "safety": 0.95,
                    "coverage": 0.7,
                    "empathy": 0.8,
                    "confidence": 0.99,
                },
            }
        )


def test_decision_mode_restriction_defaults_none() -> None:
    from diana.cognitive.models import Decision

    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_profile(),
    )
    assert decision.mode_restriction_applied is None


_NEEDS = {
    "needs_memory": False,
    "needs_policy": False,
    "needs_schedule": False,
    "needs_examples": False,
    "needs_history": True,
    "needs_context": True,
}

_EMOTION_ENUM = (
    "neutral",
    "positiva",
    "ansiosa",
    "molesta",
    "triste",
    "cariñosa",
    "urgente",
)


def test_comprehension_rejects_invalid_urgency_and_risk() -> None:
    from diana.cognitive.models import Comprehension

    with pytest.raises(ValidationError):
        Comprehension(
            intent="x",
            topics=[],
            emotion="neutral",
            urgency="urgent",  # invalid
            risk="bajo",
            **_NEEDS,
        )
    with pytest.raises(ValidationError):
        Comprehension(
            intent="x",
            topics=[],
            emotion="neutral",
            urgency="baja",
            risk="critical",  # invalid
            **_NEEDS,
        )


def test_comprehension_valid_literals() -> None:
    from diana.cognitive.models import Comprehension

    c = Comprehension(
        intent="greet",
        topics=["hello"],
        emotion="positiva",
        urgency="media",
        risk="medio",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=True,
        needs_history=True,
        needs_context=False,
    )
    assert c.needs_history is True
    assert c.needs_memory is False
    assert c.needs_policy is True
    assert c.needs_context is False
    assert c.emotion == "positiva"


@pytest.mark.parametrize("bad_emotion", ["friendly", "amistosa", "happy", ""])
def test_comprehension_rejects_unknown_emotion(bad_emotion: str) -> None:
    from diana.cognitive.models import Comprehension

    with pytest.raises(ValidationError):
        Comprehension(
            intent="x",
            topics=[],
            emotion=bad_emotion,
            urgency="baja",
            risk="bajo",
            **_NEEDS,
        )


@pytest.mark.parametrize("emotion", _EMOTION_ENUM)
def test_comprehension_accepts_all_emotion_enum_values(emotion: str) -> None:
    from diana.cognitive.models import Comprehension

    c = Comprehension(
        intent="x",
        topics=[],
        emotion=emotion,
        urgency="baja",
        risk="bajo",
        **_NEEDS,
    )
    assert c.emotion == emotion


@pytest.mark.parametrize(
    "missing_need",
    [
        "needs_memory",
        "needs_policy",
        "needs_schedule",
        "needs_examples",
        "needs_history",
        "needs_context",
    ],
)
def test_comprehension_requires_all_needs_flags(missing_need: str) -> None:
    from diana.cognitive.models import Comprehension

    data = {
        "intent": "x",
        "topics": [],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        **_NEEDS,
    }
    del data[missing_need]
    with pytest.raises(ValidationError):
        Comprehension(**data)


def test_analyst_input_and_history_message_shape() -> None:
    from diana.cognitive.models import AnalystInput, HistoryMessage

    hist = HistoryMessage(autor="dueña", texto="hola", timestamp="2026-01-01T00:00:00Z")
    inp = AnalystInput(turno_actual="¿precio?", historial_reciente=[hist])
    assert inp.turno_actual == "¿precio?"
    assert inp.historial_reciente[0].autor == "dueña"
    with pytest.raises(ValidationError):
        HistoryMessage(autor="bot", texto="x", timestamp="t")  # type: ignore[arg-type]


def test_comprehension_rejects_extra_fields() -> None:
    from diana.cognitive.models import Comprehension

    with pytest.raises(ValidationError):
        Comprehension.model_validate(
            {
                "intent": "x",
                "topics": [],
                "emotion": "neutral",
                "urgency": "baja",
                "risk": "bajo",
                **_NEEDS,
                "confidence": 0.9,
            }
        )


def test_comprehension_requires_intent() -> None:
    from diana.cognitive.models import Comprehension

    data = {
        "topics": [],
        "emotion": "neutral",
        "urgency": "baja",
        "risk": "bajo",
        **_NEEDS,
    }
    with pytest.raises(ValidationError):
        Comprehension(**data)  # type: ignore[arg-type]


def test_plan_capabilities_ok() -> None:
    from diana.cognitive.models import Plan

    plan = Plan(capabilities=["knowledge.history"])
    assert plan.capabilities == ["knowledge.history"]


def test_turn_status_terminal_and_non_terminal_set() -> None:
    from diana.cognitive.models import TERMINAL_TURN_STATUSES, TurnStatus

    terminal = {
        TurnStatus.SUPERSEDED,
        TurnStatus.DELIVERED,
        TurnStatus.FAILED,
        TurnStatus.ESCALATED,
    }
    assert TERMINAL_TURN_STATUSES == terminal
    assert TurnStatus.PENDING_APPROVAL not in TERMINAL_TURN_STATUSES
    assert TurnStatus.PENDING_APPROVAL.value == "pending_approval"

    expected_values = {
        "received",
        "analyzing",
        "planning",
        "retrieving",
        "building_context",
        "generating",
        "evaluating",
        "deciding",
        "pending_approval",
        "escalated",
        "superseded",
        "delivered",
        "failed",
    }
    assert {s.value for s in TurnStatus} == expected_values


def test_parse_turn_status_roundtrip_and_reject() -> None:
    from diana.cognitive.models import TurnStatus, parse_turn_status

    assert parse_turn_status("pending_approval") is TurnStatus.PENDING_APPROVAL
    with pytest.raises(ValueError, match="invalid turn status"):
        parse_turn_status("pending-approval")


def test_incoming_turn_constructs_and_requires_fields() -> None:
    from diana.cognitive.models import IncomingTurn

    tid = uuid4()
    turn = IncomingTurn(turn_id=tid, chat_id=1, text="hola")
    assert turn.vip_id is None
    assert turn.telegram_message_id is None
    assert turn.business_connection_id is None

    with pytest.raises(ValidationError):
        IncomingTurn(chat_id=1, text="hola")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        IncomingTurn(turn_id=tid, text="hola")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        IncomingTurn(turn_id=tid, chat_id=1)  # type: ignore[call-arg]


def _full_comprehension():
    from diana.cognitive.models import Comprehension

    return Comprehension(
        intent="chat",
        topics=["general"],
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


def test_evaluator_input_accepts_full_payload() -> None:
    from diana.cognitive.models import EvaluatorInput

    inp = EvaluatorInput(
        draft="draft text",
        comprehension=_full_comprehension(),
        included_blocks=["knowledge.history", "knowledge.context"],
        current_turn="hola",
    )
    assert inp.draft == "draft text"
    assert inp.comprehension.intent == "chat"
    assert inp.included_blocks == ["knowledge.history", "knowledge.context"]
    assert inp.current_turn == "hola"


def test_evaluator_input_rejects_extra_fields() -> None:
    from diana.cognitive.models import EvaluatorInput

    with pytest.raises(ValidationError):
        EvaluatorInput.model_validate(
            {
                "draft": "d",
                "comprehension": _full_comprehension().model_dump(),
                "included_blocks": [],
                "current_turn": "hola",
                "score_global": 0.9,
            }
        )


def test_evaluator_input_requires_all_fields() -> None:
    from diana.cognitive.models import EvaluatorInput

    base = {
        "draft": "d",
        "comprehension": _full_comprehension(),
        "included_blocks": ["knowledge.history"],
        "current_turn": "hola",
    }
    for key in ("draft", "comprehension", "included_blocks", "current_turn"):
        data = dict(base)
        del data[key]
        with pytest.raises(ValidationError):
            EvaluatorInput(**data)  # type: ignore[arg-type]


def test_built_context_accepts_prompt_and_blocks() -> None:
    from diana.cognitive.models import BuiltContext

    built = BuiltContext(
        prompt_final="## Persona\nhello\n",
        included_blocks=["knowledge.history"],
    )
    assert built.prompt_final == "## Persona\nhello\n"
    assert built.included_blocks == ["knowledge.history"]


def test_built_context_rejects_extra_fields() -> None:
    from diana.cognitive.models import BuiltContext

    with pytest.raises(ValidationError):
        BuiltContext.model_validate(
            {
                "prompt_final": "x",
                "included_blocks": [],
                "score_global": 0.9,
            }
        )


def test_built_context_requires_both_fields() -> None:
    from diana.cognitive.models import BuiltContext

    with pytest.raises(ValidationError):
        BuiltContext(prompt_final="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BuiltContext(included_blocks=[])  # type: ignore[call-arg]


def test_policy_constructs_with_minimal_fields() -> None:
    from diana.cognitive.models import Policy

    p = Policy(trigger_description="offer 10%", rule="Always offer 10% for 3+ units")
    assert p.trigger_description == "offer 10%"
    assert p.rule == "Always offer 10% for 3+ units"
    assert p.scope == "all"
    assert p.is_active is True
    assert p.source_query_id is None
    assert p.created_at is None
    assert p.id is None


def test_policy_rejects_extra_fields() -> None:
    from diana.cognitive.models import Policy
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Policy.model_validate(
            {
                "trigger_description": "x",
                "rule": "y",
                "confidence": 0.9,
            }
        )


def test_policy_requires_trigger_and_rule() -> None:
    from diana.cognitive.models import Policy
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Policy(trigger_description="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Policy(rule="y")  # type: ignore[call-arg]


def test_policy_accepts_optional_source_query_id() -> None:
    from uuid import uuid4
    from diana.cognitive.models import Policy

    qid = uuid4()
    p = Policy(trigger_description="x", rule="y", source_query_id=qid)
    assert p.source_query_id == qid


def test_policy_default_scope_is_all() -> None:
    from diana.cognitive.models import Policy

    p = Policy(trigger_description="x", rule="y")
    assert p.scope == "all"
