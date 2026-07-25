"""Unit tests for F1/F2 Decider matrix + F3 autonomous send when flag on.

Strict TDD matrix: no LLM, no score collapse, no composition wiring.
When feature_autonomous_mode is off (default), behavior is identical to F2.
"""

from __future__ import annotations

import inspect

import pytest

from diana.cognitive.decider import Decider
from diana.cognitive.models import Comprehension, Decision, EvaluationProfile
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS


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


def _high_profile(**overrides: float) -> EvaluationProfile:
    """Profile above all default autonomous mins (0.9 / 0.8 / 0.7)."""
    data = {
        "naturalness": 0.75,
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


def test_default_autonomous_thresholds_not_drop_in_for_f1_decider() -> None:
    """Dual threshold surfaces: P1 safety vs autonomous *_min send gate.

    1. Bare DEFAULT_AUTONOMOUS_THRESHOLDS as thresholds= leaves P1 at 0.3
       (key-schema landmine: safety_min is ignored for escalate).
    2. Flag on + autonomous_thresholds=DEFAULT_* + safety mid-band → approve
       (P1 passes, send gate fails on safety_min).
    3. Flag on + all dims above mins → send.
    """
    profile_mid = _profile(safety=0.5, doctrine=0.85, naturalness=0.75)
    profile_high = _high_profile()
    comp = _comprehension(risk="bajo")

    # Drop-in of F3 DEFAULT_* shape is a silent no-op for the P1 safety gate.
    drop_in = Decider(thresholds=dict(DEFAULT_AUTONOMOUS_THRESHOLDS))
    decision = drop_in.decide(profile_mid, comp)
    assert decision.action == "approve"
    assert decision.reason == "ok_for_human_review"

    # Flag on + DEFAULT autonomous mins: safety=0.5 < safety_min=0.9 → approve.
    auto_mid = Decider(
        feature_autonomous_mode=True,
        autonomous_thresholds=DEFAULT_AUTONOMOUS_THRESHOLDS,
    )
    decision_mid = auto_mid.decide(profile_mid, comp)
    assert decision_mid.action == "approve"
    assert decision_mid.reason == "autonomous_below_threshold"
    assert decision_mid.mode_restriction_applied is None

    # Flag on + high dims → send.
    decision_high = auto_mid.decide(profile_high, comp)
    assert decision_high.action == "send"
    assert decision_high.reason == "autonomous_ok"


def test_safety_equal_threshold_approves() -> None:
    decision = Decider().decide(_profile(safety=0.3), _comprehension(risk="bajo"))
    assert decision.action == "approve"
    assert decision.reason == "ok_for_human_review"


def test_never_returns_non_f2_actions() -> None:
    """Flag autonomous off + gray zone off: only approve|escalate."""
    for risk in ("bajo", "medio", "alto"):
        for safety in (0.0, 0.29, 0.3, 1.0):
            d = Decider().decide(_profile(safety=safety), _comprehension(risk=risk))
            assert d.action in ("approve", "escalate")


def test_mode_supervised_only_no_send() -> None:
    """Default Decider (flag off): supervised + high safety → approve, never send."""
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
    """Default Decider (flag off): mode alone never unlocks send."""
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
    """F.3 #2 residual (flag off): low naturalness still fall-through approve."""
    decision = Decider().decide(
        _profile(naturalness=0.1, safety=0.9),
        _comprehension(risk="bajo"),
    )
    assert decision.action == "approve"
    assert decision.reason == "ok_for_human_review"


def test_low_naturalness_does_not_produce_regenerate() -> None:
    """F.3 #2 residual (flag off): naturalness never unlocks regenerate."""
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


def test_policy_found_and_risk_alto_escalates() -> None:
    """When policy IS found and risk is alto, Decider falls through
    consult_doctrine gate and hits risk=alto gate -> escalate."""
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
        retrieved={"knowledge.policy": ["Always offer 10% for 3+ units"]},
    )
    assert decision.action == "escalate"
    assert decision.reason == "risk_high"


# ── F3 autonomous send rule ───────────────────────────────────────────


def test_flag_off_never_send_even_with_high_dims() -> None:
    """Default / feature_autonomous_mode=False + high dims + any mode → not send."""
    high = _high_profile()
    comp = _comprehension(risk="bajo")
    for mode in ("supervised", "autonomous", "unknown"):
        d_default = Decider().decide(high, comp, mode=mode)
        d_explicit = Decider(feature_autonomous_mode=False).decide(
            high, comp, mode=mode
        )
        assert d_default.action != "send"
        assert d_explicit.action != "send"
        assert d_default.action == "approve"
        assert d_explicit.action == "approve"


def test_autonomous_send_when_flag_and_all_mins_met() -> None:
    decider = Decider(feature_autonomous_mode=True)
    decision = decider.decide(
        _high_profile(),
        _comprehension(risk="bajo"),
        mode="supervised",
    )
    assert decision.action == "send"
    assert decision.reason == "autonomous_ok"
    assert decision.mode_restriction_applied is None
    assert decision.draft_text is None


def test_flag_sole_enablement_send_with_mode_supervised_is_intentional() -> None:
    """PLAN A1: feature_autonomous_mode alone unlocks send; mode is audit residual.

    mode=supervised does NOT force rewrite to approve when flag+mins are met.
    Director may still pass mode=supervised until item3 enablement plumbing.
    """
    decider = Decider(feature_autonomous_mode=True)
    decision = decider.decide(
        _high_profile(),
        _comprehension(risk="bajo"),
        mode="supervised",
    )
    assert decision.action == "send"
    assert decision.reason == "autonomous_ok"
    assert decision.mode_restriction_applied is None


@pytest.mark.parametrize(
    "dim,value",
    [
        ("safety", 0.89),
        ("doctrine", 0.79),
        ("naturalness", 0.69),
    ],
)
def test_autonomous_approve_fallback_when_dim_below_min(
    dim: str, value: float
) -> None:
    """One dim below default min; others high → approve fallback (no supervised stamp)."""
    overrides = {"safety": 0.95, "doctrine": 0.85, "naturalness": 0.75}
    overrides[dim] = value
    decider = Decider(feature_autonomous_mode=True)
    decision = decider.decide(
        _profile(**overrides),
        _comprehension(risk="bajo"),
        mode="supervised",
    )
    assert decision.action == "approve"
    assert decision.reason == "autonomous_below_threshold"
    assert decision.mode_restriction_applied is None


@pytest.mark.parametrize(
    "dim,value",
    [
        ("safety", 0.9),
        ("doctrine", 0.8),
        ("naturalness", 0.7),
    ],
)
def test_autonomous_boundary_equality_sends(dim: str, value: float) -> None:
    """Each dim exactly at default min (>=), others above → send."""
    overrides = {"safety": 0.95, "doctrine": 0.85, "naturalness": 0.75}
    overrides[dim] = value
    decider = Decider(feature_autonomous_mode=True)
    decision = decider.decide(
        _profile(**overrides),
        _comprehension(risk="bajo"),
    )
    assert decision.action == "send"
    assert decision.reason == "autonomous_ok"


def test_safety_priority_beats_autonomous_send() -> None:
    """Flag on + safety below P1 threshold → escalate, not send."""
    decider = Decider(feature_autonomous_mode=True)
    decision = decider.decide(
        _high_profile(safety=0.1),
        _comprehension(risk="bajo"),
    )
    assert decision.action == "escalate"
    assert decision.reason == "safety_below_threshold"


def test_gray_zone_priority_beats_autonomous_send() -> None:
    """Gray zone + autonomous flags + empty policy + high dims → consult_doctrine."""
    decider = Decider(
        feature_gray_zone_enabled=True,
        feature_autonomous_mode=True,
    )
    decision = decider.decide(
        _high_profile(),
        _comprehension_needs_policy(),
        retrieved={"knowledge.policy": None},
    )
    assert decision.action == "consult_doctrine"
    assert decision.reason == "doctrine_not_found"


def test_risk_alto_priority_beats_autonomous_send() -> None:
    """Autonomous flag + risk alto + high dims → escalate / risk_high, not send."""
    decider = Decider(feature_autonomous_mode=True)
    decision = decider.decide(
        _high_profile(),
        _comprehension(risk="alto"),
    )
    assert decision.action == "escalate"
    assert decision.reason == "risk_high"


def test_custom_autonomous_thresholds_change_boundary() -> None:
    custom = {
        "safety_min": 0.95,
        "doctrine_min": 0.8,
        "naturalness_min": 0.7,
    }
    decider = Decider(
        feature_autonomous_mode=True,
        autonomous_thresholds=custom,
    )
    below = decider.decide(
        _profile(safety=0.94, doctrine=0.85, naturalness=0.75),
        _comprehension(risk="bajo"),
    )
    at = decider.decide(
        _profile(safety=0.95, doctrine=0.85, naturalness=0.75),
        _comprehension(risk="bajo"),
    )
    assert below.action == "approve"
    assert below.reason == "autonomous_below_threshold"
    assert below.mode_restriction_applied is None
    assert at.action == "send"
    assert at.reason == "autonomous_ok"


def test_partial_autonomous_thresholds_merge_defaults() -> None:
    """Missing *_min keys fill from DEFAULT_AUTONOMOUS_THRESHOLDS (no KeyError)."""
    # Only override safety_min; doctrine/naturalness must stay at DEFAULT 0.8/0.7.
    decider = Decider(
        feature_autonomous_mode=True,
        autonomous_thresholds={"safety_min": 0.95},
    )
    # safety at default min 0.9 but custom min is 0.95 → short
    short = decider.decide(
        _profile(safety=0.9, doctrine=0.85, naturalness=0.75),
        _comprehension(risk="bajo"),
    )
    assert short.action == "approve"
    assert short.reason == "autonomous_below_threshold"
    # doctrine/naturalness still at defaults: doctrine 0.79 fails default 0.8
    doctrine_short = decider.decide(
        _profile(safety=0.95, doctrine=0.79, naturalness=0.75),
        _comprehension(risk="bajo"),
    )
    assert doctrine_short.action == "approve"
    assert doctrine_short.reason == "autonomous_below_threshold"
    # All meet merged mins (safety 0.95 + default doctrine/naturalness)
    ok = decider.decide(
        _profile(safety=0.95, doctrine=0.85, naturalness=0.75),
        _comprehension(risk="bajo"),
    )
    assert ok.action == "send"
    assert ok.reason == "autonomous_ok"


def test_mode_autonomous_without_flag_still_no_send() -> None:
    """mode='autonomous' alone never unlocks send when flag is False."""
    decision = Decider(feature_autonomous_mode=False).decide(
        _high_profile(),
        _comprehension(risk="bajo"),
        mode="autonomous",
    )
    assert decision.action == "approve"
    assert decision.action != "send"
    assert decision.reason == "ok_for_human_review"


def test_low_naturalness_blocks_send_when_autonomous() -> None:
    """Flag on + low naturalness + high safety/doctrine → approve, not send/regenerate."""
    decider = Decider(feature_autonomous_mode=True)
    decision = decider.decide(
        _profile(safety=0.95, doctrine=0.85, naturalness=0.1),
        _comprehension(risk="bajo"),
    )
    assert decision.action == "approve"
    assert decision.action != "send"
    assert decision.action != "regenerate"
    assert decision.reason == "autonomous_below_threshold"
    assert decision.mode_restriction_applied is None


def test_policy_empty_dict_triggers_consult_doctrine() -> None:
    """Empty dict policy_result is falsy → consult_doctrine (truthiness edge)."""
    decider = Decider(feature_gray_zone_enabled=True)
    empty = decider.decide(
        _profile(safety=0.9),
        _comprehension_needs_policy(),
        retrieved={"knowledge.policy": {}},
    )
    assert empty.action == "consult_doctrine"
    assert empty.reason == "doctrine_not_found"

    non_empty = decider.decide(
        _profile(safety=0.9),
        _comprehension_needs_policy(),
        retrieved={"knowledge.policy": {"rule": "offer 10%"}},
    )
    assert non_empty.action == "approve"
    assert non_empty.reason == "ok_for_human_review"
