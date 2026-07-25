"""F3 Decider — pure deterministic matrix: what action to take?

Answers a single question: what action to take for this turn?
Never re-judges quality, never reads draft text, never invokes a language
model provider, never collapses EvaluationProfile into a mean score or
overall/aggregate metric.

English <-> Anexo F mapping
-------------------------
| Runtime                              | Anexo F                              |
|--------------------------------------|--------------------------------------|
| EvaluationProfile                    | perfil / PerfilEvaluacion            |
| safety / naturalness / doctrine      | seguridad / naturalidad / doctrina   |
| mode: supervised | autonomous         | modo_activo (audit residual only)    |
| thresholds["safety"] (P1 escalate)   | umbrales.seguridad (F1 bare key)     |
| autonomous_thresholds safety_min etc | umbrales.seguridad_min (F3 send)     |
| action: approve | escalate | send     | accion: aprobar | escalar | enviar  |
| consult_doctrine                     | consultar_doctrina (F2)              |
| reason                               | razon                                |
| mode_restriction_applied             | restriccion_de_modo_aplicada         |

**Enablement contract (PLAN A1):** ``feature_autonomous_mode`` is the sole
send gate. ``mode`` is an audit residual only — it never unlocks or blocks
send by itself. Flag on + mins met → send even when ``mode="supervised"``
(Director may still pass supervised until item3 wiring).

F3 matrix (first match wins)
----------------------------
1. safety < P1 threshold -> escalate (reason=safety_below_threshold)
2. feature_gray_zone_enabled AND needs_policy AND no policy retrieved
   -> consult_doctrine (reason=doctrine_not_found)
3. risk == "alto" -> escalate (reason=risk_high)
4. (residual) naturalness -> re-draft loop — not implemented
5. feature_autonomous_mode AND all dims >= *_min
   -> send (reason=autonomous_ok)
6a. feature_autonomous_mode AND any dim below *_min
   -> approve (reason=autonomous_below_threshold, restriction=None)
6b. else F2 approve (reason=ok_for_human_review;
    restriction supervised_send_to_approve only when mode supervised)

P1 uses bare ``thresholds["safety"]`` (default 0.3). Autonomous send uses
separate ``autonomous_thresholds`` keys ``safety_min`` / ``doctrine_min`` /
``naturalness_min`` (defaults from DEFAULT_AUTONOMOUS_THRESHOLDS; partial
maps merge over defaults). Never mix shapes in one dict for P1.

Residual: F.3 rule 2 (naturalness re-draft loop) is not implemented;
low naturalness under autonomous only blocks send (approve fallback).
"""

from __future__ import annotations

from collections.abc import Mapping

from diana.cognitive.models import Comprehension, Decision, EvaluationProfile
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS

_DEFAULT_SAFETY_THRESHOLD = 0.3


class Decider:
    """Pure matrix: escalate / consult_doctrine / send / approve.

    Flag-gated autonomous send (feature_autonomous_mode) never collapses
    EvaluationProfile to a mean score. Default flag off = F2 parity (no send).
    ``mode`` does not enable send — only the ctor flag does.
    """

    def __init__(
        self,
        thresholds: dict | None = None,
        *,
        feature_gray_zone_enabled: bool = False,
        feature_autonomous_mode: bool = False,
        autonomous_thresholds: Mapping[str, float] | None = None,
    ) -> None:
        thresholds = thresholds or {}
        self._safety_threshold = float(
            thresholds.get("safety", _DEFAULT_SAFETY_THRESHOLD)
        )
        self._feature_gray_zone_enabled = feature_gray_zone_enabled
        self._feature_autonomous_mode = feature_autonomous_mode
        mins = dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
        if autonomous_thresholds is not None:
            mins.update(dict(autonomous_thresholds))
        self._safety_min = float(mins["safety_min"])
        self._doctrine_min = float(mins["doctrine_min"])
        self._naturalness_min = float(mins["naturalness_min"])

    def decide(
        self,
        evaluation: EvaluationProfile,
        comprehension: Comprehension,
        *,
        retrieved: dict | None = None,
        mode: str = "supervised",
    ) -> Decision:
        # 1. Safety gate (unchanged from F1) — P1 bare "safety" threshold.
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

        # 4. Residual: naturalness re-draft loop — not implemented.

        # 5–6a. Autonomous send / threshold-miss fallback (flag only; mode audit).
        if self._feature_autonomous_mode:
            if (
                evaluation.safety >= self._safety_min
                and evaluation.doctrine >= self._doctrine_min
                and evaluation.naturalness >= self._naturalness_min
            ):
                return Decision(
                    action="send",
                    reason="autonomous_ok",
                    evaluation=evaluation,
                    draft_text=None,
                    mode_restriction_applied=None,
                )
            return Decision(
                action="approve",
                reason="autonomous_below_threshold",
                evaluation=evaluation,
                draft_text=None,
                mode_restriction_applied=None,
            )

        # 6b. F2 fall-through: approve for human review.
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
