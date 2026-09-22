"""Pure decision helpers for the owner false-positive resume (AGENTS §4.21)."""

from __future__ import annotations

import pytest

from diana.application.escalation_fp_resume import (
    FP_RESUME_REASON,
    RESUME_BLOCKED_SAFETY,
    RESUME_MARKED_ONLY,
    RESUME_RESUMED,
    FpResumeOutcome,
    evaluation_from_trace,
    plan_fp_resume,
    plan_from_generated_decision,
    trace_draft,
)


def _trace(
    *,
    draft: str | None = None,
    reason: str | None = None,
    evaluation: dict | None = None,
    comprehension: dict | None = None,
    retrieved: dict | None = None,
) -> dict:
    trace: dict = {}
    if draft is not None:
        trace["generated_text"] = draft
    decision: dict = {}
    if reason is not None:
        decision["reason"] = reason
    trace["decision"] = decision
    if evaluation is not None:
        trace["evaluation"] = evaluation
    if comprehension is not None:
        trace["comprehension"] = comprehension
    if retrieved is not None:
        trace["retrieved"] = retrieved
    return trace


# --- draft source -----------------------------------------------------------


def test_reuse_when_generated_text_present() -> None:
    plan = plan_fp_resume(trace=_trace(draft="Hola, claro que sí", reason="risk_high"))

    assert plan.action == "reuse_trace_draft"
    assert plan.draft_text == "Hola, claro que sí"
    assert plan.reason == "risk_high"
    assert plan.evaluation is not None


def test_reuse_uses_decision_draft_when_generated_text_missing() -> None:
    trace = {"decision": {"reason": "risk_high", "draft_text": "borrador"}}

    assert trace_draft(trace) == "borrador"
    assert plan_fp_resume(trace=trace).action == "reuse_trace_draft"


def test_generate_when_no_draft_and_no_trace() -> None:
    assert plan_fp_resume(trace=None).action == "generate"
    assert plan_fp_resume(trace={}).action == "generate"
    assert plan_fp_resume(trace=_trace(reason="pregunta_repetida")).action == "generate"


def test_blank_draft_is_not_reused() -> None:
    assert plan_fp_resume(trace=_trace(draft="   ")).action == "generate"


# --- safety fail-closed -----------------------------------------------------


def test_safety_below_threshold_blocks_even_with_draft() -> None:
    plan = plan_fp_resume(
        trace=_trace(draft="texto inseguro", reason="safety_below_threshold")
    )

    assert plan.action == "blocked_safety"
    assert plan.draft_text == ""


def test_generated_safety_escalation_is_blocked() -> None:
    plan = plan_from_generated_decision(
        action="escalate", reason="safety_below_threshold", draft_text="texto"
    )

    assert plan.action == "blocked_safety"


def test_safety_motivo_blocks_when_the_trace_is_gone() -> None:
    """Durable fallback: the escalation ledger keeps the safety block without a trace."""
    plan = plan_fp_resume(trace=None, escalation_motivo="safety_below_threshold")

    assert plan.action == "blocked_safety"
    assert plan.draft_text == ""


def test_safety_motivo_blocks_even_with_a_reusable_draft() -> None:
    plan = plan_fp_resume(
        trace=_trace(draft="borrador", reason="risk_high"),
        escalation_motivo="safety_below_threshold",
    )

    assert plan.action == "blocked_safety"


def test_sandbox_prefixed_motivo_still_blocks() -> None:
    """The stored motivo carries the sandbox prefix, so the token is searched."""
    plan = plan_fp_resume(
        trace=None,
        escalation_motivo="SANDBOX — profile: nuevo | safety_below_threshold",
    )

    assert plan.action == "blocked_safety"


@pytest.mark.parametrize("motivo", [None, "", "   ", "risk_high", "pregunta_repetida"])
def test_other_motivos_do_not_block(motivo: str | None) -> None:
    plan = plan_fp_resume(
        trace=_trace(draft="borrador", reason="risk_high"), escalation_motivo=motivo
    )

    assert plan.action == "reuse_trace_draft"


def test_generated_risk_escalation_with_draft_is_not_a_failure() -> None:
    """Mirrors the doctrine regen contract: escalate by risk + draft → owner decides."""
    plan = plan_from_generated_decision(
        action="escalate", reason="risk_high", draft_text="borrador válido"
    )

    assert plan.action == "reuse_trace_draft"
    assert plan.draft_text == "borrador válido"


# --- generated decision fail-closed ----------------------------------------


@pytest.mark.parametrize("action", ["approve", "send", "escalate"])
def test_empty_generated_draft_blocks(action: str) -> None:
    assert (
        plan_from_generated_decision(action=action, reason="r", draft_text="  ").action
        == "blocked_no_text"
    )


def test_consult_doctrine_blocks() -> None:
    plan = plan_from_generated_decision(
        action="consult_doctrine", reason="doctrine_not_found", draft_text="texto"
    )

    assert plan.action == "blocked_no_text"
    assert plan.reason == "doctrine_not_found"


def test_empty_draft_keeps_the_safety_reason() -> None:
    """The safety label rides on the reason, so an empty draft does not lose it."""
    plan = plan_from_generated_decision(
        action="escalate", reason="safety_below_threshold", draft_text="   "
    )

    assert plan.action == "blocked_no_text"
    assert plan.reason == "safety_below_threshold"


# --- evaluation parsing -----------------------------------------------------


def test_evaluation_from_trace_validates_dims() -> None:
    profile = evaluation_from_trace(
        _trace(
            evaluation={
                "naturalness": 0.9,
                "precision": 0.8,
                "doctrine": 0.7,
                "consistency": 0.6,
                "safety": 0.5,
                "coverage": 0.4,
                "empathy": 0.3,
            }
        )
    )

    assert profile.naturalness == 0.9
    assert profile.empathy == 0.3


@pytest.mark.parametrize(
    "evaluation",
    [
        None,
        {},
        {"naturalness": "alta"},
        {"safety": 5.0},
        {"naturalness": 0.5},
    ],
)
def test_evaluation_falls_back_to_neutral(evaluation: dict | None) -> None:
    """A persisted vector that is not a valid 7-dim profile never raises."""
    profile = evaluation_from_trace(
        _trace(evaluation=evaluation) if evaluation is not None else {}
    )

    assert profile.safety == 0.5
    assert profile.naturalness == 0.5


def test_comprehension_and_retrieved_are_carried_for_the_dm() -> None:
    plan = plan_fp_resume(
        trace=_trace(
            draft="d",
            reason="risk_high",
            comprehension={"needs_policy": False},
            retrieved={"knowledge.policy": []},
        )
    )

    assert plan.comprehension == {"needs_policy": False}
    assert plan.retrieved == {"knowledge.policy": []}


# --- outcome tokens ---------------------------------------------------------


def test_outcome_defaults_and_tokens() -> None:
    assert FpResumeOutcome(marked=True, status=RESUME_RESUMED).detail == ""
    assert RESUME_RESUMED != RESUME_MARKED_ONLY != RESUME_BLOCKED_SAFETY
    assert FP_RESUME_REASON == "escalation_false_positive_resume"
