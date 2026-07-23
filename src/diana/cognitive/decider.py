"""F1 Decider — pure deterministic matrix: what action to take?

Answers a single question: what action to take for this turn?
Never re-judges quality, never reads draft text, never invokes a language
model provider, never collapses EvaluationProfile into a mean score or
overall/aggregate metric.

English ↔ Anexo F mapping
-------------------------
| Runtime                         | Anexo F                              |
|---------------------------------|--------------------------------------|
| EvaluationProfile               | perfil / PerfilEvaluacion            |
| safety / naturalness            | seguridad / naturalidad              |
| mode: supervised | autonomous    | modo_activo: supervisado | autonomo  |
| thresholds["safety"]            | umbrales.seguridad_min               |
| naturalness_min                 | unused in F1 (residual with F.3 #2)  |
| action: approve | escalate      | accion: aprobar | escalar            |
| reason                          | razon                                |
| mode_restriction_applied        | restriccion_de_modo_aplicada         |
| risk == alto escalate           | F1 extension beyond pure F.3 table   |

F1 matrix (first match wins)
----------------------------
1. safety < threshold → escalate (reason=safety_below_threshold)
2. risk == "alto" → escalate (reason=risk_high)  — F1 extension after safety
3. else → approve (reason=ok_for_human_review)

Residual: F.3 rule 2 (naturalness → re-draft loop) is not implemented in F1;
fall-through is supervised approve. Public actions are only approve|escalate;
raw send is never returned. On supervised approve, mode_restriction_applied
records the conceptual send→approve rewrite as "supervised_send_to_approve".
"""

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
        # Never read draft text. Pure matrix. No score collapse.
        if evaluation.safety < self._safety_threshold:
            return Decision(
                action="escalate",
                reason="safety_below_threshold",
                evaluation=evaluation,
                draft_text=None,
                mode_restriction_applied=None,
            )
        if comprehension.risk == "alto":
            return Decision(
                action="escalate",
                reason="risk_high",
                evaluation=evaluation,
                draft_text=None,
                mode_restriction_applied=None,
            )
        # F.3 #2 residual: naturalness gate not implemented → fall through here.
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
