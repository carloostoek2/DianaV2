"""Unit tests for F1 Decider matrix (no LLM, no score collapse)."""

from __future__ import annotations

import inspect

import pytest

from diana.cognitive.decider import Decider
from diana.cognitive.models import Comprehension, Decision, EvaluationProfile


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


def _comprehension(*, risk: str = "bajo") -> Comprehension:
    return Comprehension(
        intent="chat",
        topics=["x"],
        emotion="neutral",
        urgency="baja",
        risk=risk,  # type: ignore[arg-type]
    )


def test_approve_when_safe_and_risk_not_alto() -> None:
    decision = Decider().decide(_profile(safety=0.5), _comprehension(risk="medio"))
    assert decision.action == "approve"
    assert decision.reason == "ok_for_human_review"
    assert decision.evaluation.safety == 0.5


def test_escalate_when_safety_below_default_threshold() -> None:
    decision = Decider().decide(_profile(safety=0.29), _comprehension(risk="bajo"))
    assert decision.action == "escalate"
    assert decision.reason == "safety_below_threshold"


def test_escalate_when_risk_alto_even_if_safety_ok() -> None:
    decision = Decider().decide(_profile(safety=0.9), _comprehension(risk="alto"))
    assert decision.action == "escalate"
    assert decision.reason == "risk_high"


def test_safety_takes_priority_over_risk() -> None:
    decision = Decider().decide(_profile(safety=0.1), _comprehension(risk="alto"))
    assert decision.action == "escalate"
    assert decision.reason == "safety_below_threshold"


def test_custom_safety_threshold() -> None:
    decider = Decider(thresholds={"safety": 0.8})
    assert (
        decider.decide(_profile(safety=0.79), _comprehension()).action == "escalate"
    )
    assert (
        decider.decide(_profile(safety=0.8), _comprehension()).action == "approve"
    )


def test_safety_equal_threshold_approves() -> None:
    decision = Decider().decide(_profile(safety=0.3), _comprehension(risk="bajo"))
    assert decision.action == "approve"
    assert decision.reason == "ok_for_human_review"


def test_never_returns_non_f1_actions() -> None:
    for risk in ("bajo", "medio", "alto"):
        for safety in (0.0, 0.29, 0.3, 1.0):
            d = Decider().decide(_profile(safety=safety), _comprehension(risk=risk))
            assert d.action in ("approve", "escalate")


def test_mode_supervised_only_no_send() -> None:
    d = Decider().decide(
        _profile(safety=0.9),
        _comprehension(risk="bajo"),
        mode="supervised",
    )
    assert d.action == "approve"
    assert d.action != "send"


@pytest.mark.parametrize(
    "mode",
    ["supervised", "autonomous", "unknown", "", "send"],
)
def test_mode_never_produces_send_action(mode: str) -> None:
    """F1 matrix only approve|escalate — mode cannot unlock send."""
    approve = Decider().decide(
        _profile(safety=0.9),
        _comprehension(risk="bajo"),
        mode=mode,
    )
    escalate = Decider().decide(
        _profile(safety=0.1),
        _comprehension(risk="alto"),
        mode=mode,
    )
    assert approve.action == "approve"
    assert escalate.action == "escalate"
    assert approve.action != "send"
    assert escalate.action != "send"
    assert approve.action in ("approve", "escalate")
    assert escalate.action in ("approve", "escalate")


def test_decider_source_has_no_mean_or_llm() -> None:
    from diana.cognitive import decider as decider_mod

    source = inspect.getsource(decider_mod)
    assert "mean(" not in source
    assert "overall_score" not in source
    assert "confidence" not in source
    assert "LLM" not in source
    assert "generate" not in source


def test_decision_type_is_domain_model() -> None:
    d = Decider().decide(_profile(), _comprehension())
    assert isinstance(d, Decision)
    assert d.draft_text is None
