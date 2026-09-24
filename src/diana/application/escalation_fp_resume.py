"""Pure decision helpers for the owner false-positive resume (no I/O).

When the owner marks an escalation as a false positive, the flow continues with
the normal supervised draft (see AGENTS §4.21). This module decides *where the
draft comes from* without touching Telegram, the DB or the LLM:

- ``reuse_trace_draft``: the pipeline already generated a draft before the
  Decider escalated (``pipeline_traces.generated_text``) — reuse it as-is.
- ``generate``: no draft exists (H4 ``pregunta_repetida``, deterministic
  escalations) — the caller re-runs the pipeline for the same turn.
- ``blocked_safety``: the escalation was ``safety_below_threshold``, so the
  draft failed the safety gate. Fail closed: never enqueue an unsafe draft
  (same rule as the doctrine regen, ``AdminService.resolve_doctrine_rule_and_enqueue``).
  The reason comes from the trace and, when the trace is gone (TTL purge, read
  fault), from the persisted ``escalation_events.motivo``.
- ``blocked_no_text``: nothing usable to show (empty draft, or the regenerated
  decision asks for doctrine instead of a reply).

Machine tokens stay stable English/snake_case for stores and parsers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from diana.cognitive.models import EvaluationProfile

__all__ = [
    "FP_RESUME_REASON",
    "RESUME_BLOCKED_SAFETY",
    "RESUME_MARKED_ONLY",
    "RESUME_RESUMED",
    "SAFETY_ESCALATION_REASON",
    "FpResumeAction",
    "FpResumeKey",
    "FpResumeOutcome",
    "FpResumePlan",
    "evaluation_from_trace",
    "fp_resume_key",
    "plan_fp_resume",
    "plan_from_generated_decision",
    "trace_decision_reason",
    "trace_draft",
]

FpResumeAction = Literal[
    "reuse_trace_draft",
    "generate",
    "blocked_safety",
    "blocked_no_text",
]

# Decider reason for a draft that failed the safety gate (fail closed).
SAFETY_ESCALATION_REASON = "safety_below_threshold"
# Synthetic decision reason for the resumed supervised draft (display-only).
FP_RESUME_REASON = "escalation_false_positive_resume"

# Outcome statuses of ``AdminService.mark_false_positive_and_resume``.
RESUME_RESUMED = "resumed_with_draft"
RESUME_MARKED_ONLY = "marked_only"
RESUME_BLOCKED_SAFETY = "blocked_safety"

# Owner-facing reason keys: the closed vocabulary both entry points (DM button
# and /fp command) map to their own token + message. ``Outcome.detail`` is the
# machine token; this is the *why* the owner gets told.
FpResumeKey = Literal[
    "draft_sent",
    "blocked_safety",
    "skipped_new_turn",
    "skipped_owner_wrote",
    "skipped_no_vip_text",
    "skipped_no_draft_generated",
    "skipped_no_connection",
    "skipped_unavailable",
    "skipped_in_progress",
    "skipped_error",
    "stale",
    "marked",
    "failed",
]

# Fail-closed details → owner-facing reason key. "marked" is the fallback so an
# unknown/future detail never invents a message the owner would not understand.
_DETAIL_KEYS: dict[str, FpResumeKey] = {
    "chat_busy": "skipped_new_turn",
    "owner_intervened": "skipped_owner_wrote",
    # Distinct owner copy: missing VIP text vs generation that produced nothing
    # usable (empty draft / doctrine re-request today). Do not collapse them.
    "no_vip_text": "skipped_no_vip_text",
    "no_draft_generated": "skipped_no_draft_generated",
    "no_business_connection": "skipped_no_connection",
    "no_director": "skipped_unavailable",
    "already_running": "skipped_in_progress",
    "error": "skipped_error",
    "superseded": "skipped_error",
    "reopen_lost": "skipped_error",
    "approval_exists": "skipped_error",
    "cancelled_not_deleted": "skipped_error",
    "missing_turn": "stale",
    "not_escalated": "stale",
    "stale": "stale",
    "flag_off": "marked",
}

# Decider action that asks for a business rule instead of a reply.
_CONSULT_DOCTRINE = "consult_doctrine"
_ESCALATE = "escalate"

_EVAL_DIMS = (
    "naturalness",
    "precision",
    "doctrine",
    "consistency",
    "safety",
    "coverage",
    "empathy",
)


def _neutral_evaluation() -> EvaluationProfile:
    """Fallback profile when the persisted evaluation is missing/unusable.

    Mirrors ``create_supervised_delivery_from_gray_zone``: a supervised draft
    with an honest neutral vector rather than an inferred one.
    """
    return EvaluationProfile(**dict.fromkeys(_EVAL_DIMS, 0.5))


@dataclass(frozen=True)
class FpResumePlan:
    """Where the resumed draft comes from, plus the trace context for the DM."""

    action: FpResumeAction
    reason: str
    draft_text: str = ""
    evaluation: EvaluationProfile | None = None
    comprehension: Mapping[str, Any] | None = None
    retrieved: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class FpResumeOutcome:
    """Result of the owner false-positive tap (mark + optional resume).

    ``marked`` mirrors the metric mark store (False → the mark could not be
    recorded, which the owner surfaces as an error). ``status`` is one of the
    ``RESUME_*`` constants and ``detail`` is a machine token for logs and for
    the honest owner message when nothing was resumed.
    """

    marked: bool
    status: str
    detail: str = ""


def fp_resume_key(outcome: FpResumeOutcome) -> FpResumeKey:
    """Owner-facing reason key for a false-positive tap.

    Single source of truth for both presentation layers: the escalation DM
    button and the ``/fp`` command derive their token and message from this key
    (``escalation_fp_<key>`` / ``fp_<key>``).
    """
    if not outcome.marked:
        return "failed"
    if outcome.status == RESUME_RESUMED:
        return "draft_sent"
    if outcome.status == RESUME_BLOCKED_SAFETY:
        return "blocked_safety"
    return _DETAIL_KEYS.get(outcome.detail, "marked")


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _trace_decision(trace: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Persisted ``decision`` JSONB from the trace, when present."""
    return _as_mapping(_as_mapping(trace or {}).get("decision"))


def trace_decision_reason(trace: Mapping[str, Any] | None) -> str:
    """Reason of the persisted decision; empty string when unavailable."""
    decision = _trace_decision(trace)
    if decision is None:
        return ""
    reason = decision.get("reason")
    return reason.strip() if isinstance(reason, str) else ""


def trace_draft(trace: Mapping[str, Any] | None) -> str:
    """Draft the pipeline generated for this turn (empty when none).

    ``generated_text`` is the canonical column (the same one /traza and the
    outcome ledger read); ``decision.draft_text`` is the fallback for rows
    written by a decision-only path.
    """
    bucket = _as_mapping(trace or {})
    if bucket is None:
        return ""
    generated = bucket.get("generated_text")
    if isinstance(generated, str) and generated.strip():
        return generated.strip()
    decision = _trace_decision(bucket)
    if decision is not None:
        draft = decision.get("draft_text")
        if isinstance(draft, str) and draft.strip():
            return draft.strip()
    return ""


def evaluation_from_trace(trace: Mapping[str, Any] | None) -> EvaluationProfile:
    """Validated evaluation profile from the trace, neutral when unusable."""
    raw = _as_mapping(_as_mapping(trace or {}).get("evaluation"))
    if raw is None:
        return _neutral_evaluation()
    values = {dim: raw.get(dim) for dim in _EVAL_DIMS}
    if any(
        not isinstance(v, (int, float)) or isinstance(v, bool)
        for v in values.values()
    ):
        return _neutral_evaluation()
    try:
        return EvaluationProfile(
            **{dim: float(value) for dim, value in values.items()}  # type: ignore[arg-type]
        )
    except ValueError:
        return _neutral_evaluation()


def plan_fp_resume(
    *,
    trace: Mapping[str, Any] | None,
    escalation_motivo: str | None = None,
) -> FpResumePlan:
    """Decide the draft source for a false-positive resume.

    Safety wins over an existing draft: a draft that failed the safety gate is
    never enqueued, not even for the owner's queue. The escalation reason comes
    from the persisted decision, which every escalation that ran the pipeline
    has (semantic, safety and H4); ``escalation_motivo`` is the durable
    fallback for a trace that is gone (TTL purge, read fault), so a safety
    escalation cannot silently degrade into a full re-run. Deterministic
    escalations never escalate for safety, so both sources absent falls through
    to generation.
    """
    reason = trace_decision_reason(trace)
    motivo = (escalation_motivo or "").strip()
    # The persisted motivo may carry a sandbox prefix ("SANDBOX — profile: x |
    # reason"), so the token is looked for inside it instead of compared whole.
    if reason == SAFETY_ESCALATION_REASON or SAFETY_ESCALATION_REASON in motivo:
        return FpResumePlan(action="blocked_safety", reason=SAFETY_ESCALATION_REASON)

    draft = trace_draft(trace)
    if draft:
        return FpResumePlan(
            action="reuse_trace_draft",
            reason=reason or FP_RESUME_REASON,
            draft_text=draft,
            evaluation=evaluation_from_trace(trace),
            comprehension=_as_mapping(_as_mapping(trace or {}).get("comprehension")),
            retrieved=_as_mapping(_as_mapping(trace or {}).get("retrieved")),
        )
    return FpResumePlan(action="generate", reason=reason or FP_RESUME_REASON)


def plan_from_generated_decision(
    *,
    action: str,
    reason: str,
    draft_text: str,
) -> FpResumePlan:
    """Validate a freshly generated decision (fail-closed rules).

    Mirrors the doctrine regen contract: ``consult_doctrine``, an empty draft
    and an ``escalate`` by safety are blocked. An ``escalate`` by
    risk/frustration with a valid draft is NOT a failure — the owner decides
    from her approval queue.
    """
    draft = (draft_text or "").strip()
    if not draft:
        return FpResumePlan(action="blocked_no_text", reason=reason)
    if action == _CONSULT_DOCTRINE:
        return FpResumePlan(action="blocked_no_text", reason=reason)
    if action == _ESCALATE and reason == SAFETY_ESCALATION_REASON:
        return FpResumePlan(action="blocked_safety", reason=reason)
    return FpResumePlan(action="reuse_trace_draft", reason=reason, draft_text=draft)
