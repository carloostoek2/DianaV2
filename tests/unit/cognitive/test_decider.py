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
        needs_memory=False,
        needs_policy=False,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
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


def test_never_returns_non_f2_actions() -> None:
    """F1 matrix only approve|escalate when gray zone disabled (default)."""
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


def test_low_naturalness_still_approves_when_safety_ok() -> None:
    """F.3 #2 residual: low naturalness does not change F1 action (fall-through approve)."""
    decision = Decider().decide(
        _profile(naturalness=0.1, safety=0.9),
        _comprehension(risk="bajo"),
    )
    assert decision.action == "approve"
    assert decision.reason == "ok_for_human_review"


def test_low_naturalness_does_not_produce_regenerate() -> None:
    """F.3 #2 residual: naturalness never unlocks regenerate in F1."""
    decision = Decider().decide(
        _profile(naturalness=0.1, safety=0.9),
        _comprehension(risk="medio"),
    )
    assert decision.action != "regenerate"
    assert decision.action in ("approve", "escalate")


def test_mode_restriction_set_on_supervised_approve() -> None:
    decision = Decider().decide(
        _profile(safety=0.9),
        _comprehension(risk="bajo"),
        mode="supervised",
    )
    assert decision.action == "approve"
    assert decision.mode_restriction_applied == "supervised_send_to_approve"


def test_mode_restriction_none_on_escalate_safety() -> None:
    decision = Decider().decide(
        _profile(safety=0.1),
        _comprehension(risk="bajo"),
        mode="supervised",
    )
    assert decision.action == "escalate"
    assert decision.reason == "safety_below_threshold"
    assert decision.mode_restriction_applied is None


def test_mode_restriction_none_on_escalate_risk() -> None:
    decision = Decider().decide(
        _profile(safety=0.9),
        _comprehension(risk="alto"),
        mode="supervised",
    )
    assert decision.action == "escalate"
    assert decision.reason == "risk_high"
    assert decision.mode_restriction_applied is None


def test_mode_restriction_none_when_mode_not_supervised() -> None:
    decision = Decider().decide(
        _profile(safety=0.9),
        _comprehension(risk="bajo"),
        mode="autonomous",
    )
    assert decision.action == "approve"
    assert decision.mode_restriction_applied is None


# ── F2 consult_doctrine rule ──────────────────────────────────────────


def _comprehension_needs_policy() -> Comprehension:
    return Comprehension(
        intent="consulta_comercial",
        topics=["precios"],
        emotion="neutral",
        urgency="media",
        risk="bajo",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
    )


def test_consult_doctrine_when_no_policy_and_flag_enabled() -> None:
    decider = Decider(feature_gray_zone_enabled=True)
    decision = decider.decide(
        _profile(safety=0.9),
        _comprehension_needs_policy(),
        retrieved={"knowledge.policy": None},
    )
    assert decision.action == "consult_doctrine"
    assert decision.reason == "doctrine_not_found"


def test_consult_doctrine_when_policy_list_empty() -> None:
    """Empty list (no match) should also trigger consult_doctrine."""
    decider = Decider(feature_gray_zone_enabled=True)
    decision = decider.decide(
        _profile(safety=0.9),
        _comprehension_needs_policy(),
        retrieved={"knowledge.policy": []},
    )
    assert decision.action == "consult_doctrine"
    assert decision.reason == "doctrine_not_found"


def test_no_consult_doctrine_when_flag_disabled() -> None:
    """F1 backward compat: gray zone disabled falls through to approve."""
    decider = Decider(feature_gray_zone_enabled=False)
    decision = decider.decide(
        _profile(safety=0.9),
        _comprehension_needs_policy(),
        retrieved={"knowledge.policy": None},
    )
    assert decision.action == "approve"


def test_no_consult_doctrine_when_policy_found() -> None:
    """Policy exists — falls through to approve."""
    decider = Decider(feature_gray_zone_enabled=True)
    decision = decider.decide(
        _profile(safety=0.9),
        _comprehension_needs_policy(),
        retrieved={"knowledge.policy": ["Always offer 10% for 3+ units"]},
    )
    assert decision.action == "approve"


def test_no_consult_doctrine_when_needs_policy_false() -> None:
    """Even with flag enabled, needs_policy=False should not trigger."""
    decider = Decider(feature_gray_zone_enabled=True)
    decision = decider.decide(
        _profile(safety=0.9),
        _comprehension(risk="bajo"),
        retrieved={"knowledge.policy": None},
    )
    assert decision.action == "approve"


def test_retrieved_none_does_not_crash() -> None:
    """Default retrieved=None should not crash Decider."""
    decider = Decider(feature_gray_zone_enabled=True)
    decision = decider.decide(
        _profile(safety=0.9),
        _comprehension_needs_policy(),
    )
    assert decision.action == "consult_doctrine"


def test_safety_wins_over_doctrine() -> None:
    """Priority 1 (safety) still wins over priority 2 (doctrine)."""
    decider = Decider(feature_gray_zone_enabled=True)
    decision = decider.decide(
        _profile(safety=0.1),
        _comprehension_needs_policy(),
        retrieved={"knowledge.policy": None},
    )
    assert decision.action == "escalate"
    assert decision.reason == "safety_below_threshold"


def test_doctrine_wins_over_risk_alto() -> None:
    """Priority 2 (doctrine) fires before priority 3 (risk alto).

    When both conditions are true — needs_policy + no policy + risk alto —
    consult_doctrine wins. The owner provides doctrine which may resolve the risk.
    """
    decider = Decider(feature_gray_zone_enabled=True)
    comp = Comprehension(
        intent="consulta_comercial",
        topics=["precios"],
        emotion="neutral",
        urgency="media",
        risk="alto",
        needs_memory=False,
        needs_policy=True,
        needs_schedule=False,
        needs_examples=False,
        needs_history=True,
        needs_context=True,
    )
    decision = decider.decide(
        _profile(safety=0.9),
        comp,
        retrieved={"knowledge.policy": None},
    )
    assert decision.action == "consult_doctrine"
    assert decision.reason == "doctrine_not_found"
