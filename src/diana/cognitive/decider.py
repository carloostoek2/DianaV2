"""F2 Decider — pure deterministic matrix: what action to take?

Answers a single question: what action to take for this turn?
Never re-judges quality, never reads draft text, never invokes a language
model provider, never collapses EvaluationProfile into a mean score or
overall/aggregate metric.

English <-> Anexo F mapping
-------------------------
| Runtime                         | Anexo F                              |
|---------------------------------|--------------------------------------|
| EvaluationProfile               | perfil / PerfilEvaluacion            |
| safety / naturalness            | seguridad / naturalidad              |
| mode: supervised | autonomous    | modo_activo: supervisado | autonomo  |
| thresholds["safety"]            | umbrales.seguridad_min               |
| action: approve | escalate      | accion: aprobar | escalar            |
| consult_doctrine                | consultar_doctrina (F2 new)          |
| reason                          | razon                                |
| mode_restriction_applied        | restriccion_de_modo_aplicada         |

F2 matrix (first match wins)
----------------------------
1. safety < threshold -> escalate (reason=safety_below_threshold)
2. feature_gray_zone_enabled AND needs_policy AND no policy retrieved -> consult_doctrine
3. risk == "alto" -> escalate (reason=risk_high)
4. else -> approve (reason=ok_for_human_review)

Residual: F.3 rule 2 (naturalness -> re-draft loop) is not implemented.
"""

from __future__ import annotations

from diana.cognitive.models import Comprehension, Decision, EvaluationProfile

_DEFAULT_SAFETY_THRESHOLD = 0.3


class Decider:
    """F2 supervised matrix: escalate on low safety; consult_doctrine on missing
    policy; escalate on high risk; else approve.

    Never returns non-F2 actions outside approve|escalate|consult_doctrine.
    Never collapses EvaluationProfile to a single aggregate score.
    """

    def __init__(
        self,
        thresholds: dict | None = None,
        *,
        feature_gray_zone_enabled: bool = False,
    ) -> None:
        thresholds = thresholds or {}
        self._safety_threshold = float(
            thresholds.get("safety", _DEFAULT_SAFETY_THRESHOLD)
        )
        self._feature_gray_zone_enabled = feature_gray_zone_enabled

    def decide(
        self,
        evaluation: EvaluationProfile,
        comprehension: Comprehension,
        *,
        retrieved: dict | None = None,
        mode: str = "supervised",
    ) -> Decision:
        # 1. Safety gate (unchanged from F1).
        if evaluation.safety < self._safety_threshold:
            return Decision(
                action="escalate",
                reason="safety_below_threshold",
                evaluation=evaluation,
                draft_text=None,
                mode_restriction_applied=None,
            )

        # 2. Gray zone: needs_policy but no policy found AND feature enabled.
        if self._feature_gray_zone_enabled and comprehension.needs_policy:
            policy_result = (retrieved or {}).get("knowledge.policy")
            if not policy_result:
                return Decision(
                    action="consult_doctrine",
                    reason="doctrine_not_found",
                    evaluation=evaluation,
                    draft_text=None,
                    mode_restriction_applied=None,
                )

        # 3. High risk (unchanged from F1).
        if comprehension.risk == "alto":
            return Decision(
                action="escalate",
                reason="risk_high",
                evaluation=evaluation,
                draft_text=None,
                mode_restriction_applied=None,
            )

        # 4. Fall-through: approve for human review.
        restriction = (
            "supervised_send_to_approve" if mode == "supervised" else None
        )
        return Decision(
            action="approve",
            reason="ok_for_human_review",
            evaluation=evaluation,
            draft_text=None,
            mode_restriction_applied=restriction,
        )
