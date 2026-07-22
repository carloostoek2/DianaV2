"""F1 Decider — pure matrix over EvaluationProfile.safety and risk."""

from __future__ import annotations

from diana.cognitive.models import Comprehension, Decision, EvaluationProfile

_DEFAULT_SAFETY_THRESHOLD = 0.3


class Decider:
    """F1 supervised matrix: escalate on low safety or high risk; else approve.

    Never returns non-F1 actions outside approve|escalate.
    Never collapses EvaluationProfile to a single aggregate score.
    """

    def __init__(self, thresholds: dict | None = None) -> None:
        thresholds = thresholds or {}
        self._safety_threshold = float(
            thresholds.get("safety", _DEFAULT_SAFETY_THRESHOLD)
        )

    def decide(
        self,
        evaluation: EvaluationProfile,
        comprehension: Comprehension,
        *,
        mode: str = "supervised",
    ) -> Decision:
        # mode is accepted for future filters; F1 is always supervised and
        # never maps to send.
        _ = mode
        if evaluation.safety < self._safety_threshold:
            return Decision(
                action="escalate",
                reason="safety_below_threshold",
                evaluation=evaluation,
                draft_text=None,
            )
        if comprehension.risk == "alto":
            return Decision(
                action="escalate",
                reason="risk_high",
                evaluation=evaluation,
                draft_text=None,
            )
        return Decision(
            action="approve",
            reason="ok_for_human_review",
            evaluation=evaluation,
            draft_text=None,
        )
