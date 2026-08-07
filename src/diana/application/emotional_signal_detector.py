"""EmotionalSignalDetector — heuristic v1 (no LLM per turn), shadow-only.

Maps the analyst output (``comprehension``) + a rolling emotional baseline
(prior turns per chat) + the Decider action to an :class:`EmotionalSignalRecord`.
Pure application service: no aiogram, no DB, no LLM (import-purity preserved).

Thresholds are fixed constants with a **manual** override via ``apply_overrides``
(hydrated from ``system_config`` key ``emotional_detector`` at boot). They are
NEVER auto-calibrated by the LLM (incident lesson — safety gates stay constants).
"""

from __future__ import annotations

from typing import Any

from diana.application.ports import EmotionalSignalRecord
from diana.cognitive.models import Comprehension, SignalType

# Fixed thresholds (constants, never auto-calibrated). Manual override only.
SYNTHESIS_THRESHOLD = 0.5
ESCALATE_THRESHOLD = 0.8
MIN_BASELINE_TURNS = 5
BASELINE_WARM_RATIO_OPEN = 0.4
BASELINE_WARM_RATIO_COOL = 0.7

_ANGUISH_EMOTIONS = frozenset({"ansiosa", "molesta", "triste"})
_VULNERABILITY_EMOTIONS = frozenset({"triste", "ansiosa"})
_PERSONAL_OPENING_INTENTS = frozenset(
    {"pedir_consejo", "contar_anecdota", "compartir_logro"}
)
_PERSONAL_OPENING_TOPICS = frozenset(
    {"apertura", "honestidad", "conexion", "tema_pesado"}
)
# ``honestidad``/``extrañar`` are analyst "useful tags" (analyst.py:44-53),
# not mandatory topics — match both sets; a missing tag is simply "no signal".
_REVELATION_TOPICS = frozenset(
    {"honestidad", "tema_pesado", "extrañar", "reencuentro", "conexion"}
)
_WARM_EMOTIONS = frozenset({"positiva", "cariñosa"})
_COLD_EMOTIONS = frozenset({"triste", "ansiosa", "molesta"})


class EmotionalSignalDetector:
    """Heuristic emotional-break detector (SPEC-EVOLUCION-AGENTE v1.2).

    Signal priority when several match (most urgent wins, single output):
    ``angustia`` > ``vulnerabilidad`` > ``revelacion_de_vida`` >
    ``ruptura_de_patron``.
    """

    def __init__(
        self,
        synthesis_threshold: float = SYNTHESIS_THRESHOLD,
        escalate_threshold: float = ESCALATE_THRESHOLD,
        min_baseline_turns: int = MIN_BASELINE_TURNS,
    ) -> None:
        self.synthesis_threshold = float(synthesis_threshold)
        self.escalate_threshold = float(escalate_threshold)
        self.min_baseline_turns = int(min_baseline_turns)

    def apply_overrides(self, config: dict[str, Any]) -> None:
        """Manual threshold override from ``system_config`` (key ``emotional_detector``).

        This is the ONLY override point — thresholds are never auto-calibrated.
        Missing keys are ignored; invalid values are rejected without crashing.
        """
        if not isinstance(config, dict):
            return
        try:
            raw = config.get("synthesis_threshold")
            if raw is not None:
                value = float(raw)
                if 0.0 <= value <= 1.0:
                    self.synthesis_threshold = value
        except (TypeError, ValueError):
            pass
        try:
            raw = config.get("escalate_threshold")
            if raw is not None:
                value = float(raw)
                if 0.0 <= value <= 1.0:
                    self.escalate_threshold = value
        except (TypeError, ValueError):
            pass
        try:
            raw = config.get("min_baseline_turns")
            if raw is not None:
                value = int(raw)
                if value >= 1:
                    self.min_baseline_turns = value
        except (TypeError, ValueError):
            pass

    def detect(
        self,
        comprehension: dict[str, Any] | Comprehension | None,
        baseline: list[dict[str, Any]] | None,
        decision_action: str | None,
    ) -> EmotionalSignalRecord:
        """Map comprehension + baseline + decision action to an emotional signal.

        ``comprehension`` may be the persisted dict (from ``pipeline_traces``)
        or a :class:`Comprehension` model. ``baseline`` is a list of prior-turn
        comprehension dicts (newest first), used by ``ruptura_de_patron``.
        """
        comp = self._comprehension_dict(comprehension)
        if comp is None:
            return self._no_signal(decision_action)

        # angustia (0.85): most urgent — emotion in {ansiosa, molesta, triste}
        # AND urgency alta AND risk in {medio, alto}.
        emotion = self._get(comp, "emotion")
        urgency = self._get(comp, "urgency")
        risk = self._get(comp, "risk")
        if (
            emotion in _ANGUISH_EMOTIONS
            and urgency == "alta"
            and risk in {"medio", "alto"}
        ):
            return self._build(
                signal_type="angustia", intensity=0.85, decision_action=decision_action
            )

        # vulnerabilidad (0.6): emotion in {triste, ansiosa} AND personal opening.
        intent = self._get(comp, "intent")
        topics = self._topics(comp)
        if emotion in _VULNERABILITY_EMOTIONS and (
            intent in _PERSONAL_OPENING_INTENTS
            or bool(topics & _PERSONAL_OPENING_TOPICS)
        ):
            return self._build(
                signal_type="vulnerabilidad",
                intensity=0.6,
                decision_action=decision_action,
            )

        # revelacion_de_vida (0.5): topics intersect revelation set.
        if bool(topics & _REVELATION_TOPICS):
            return self._build(
                signal_type="revelacion_de_vida",
                intensity=0.5,
                decision_action=decision_action,
            )

        # ruptura_de_patron (0.55): needs a real baseline (>= MIN_BASELINE_TURNS).
        warm_ratio = self._baseline_warm_ratio(baseline)
        if warm_ratio is not None:
            if emotion in _WARM_EMOTIONS and warm_ratio < BASELINE_WARM_RATIO_OPEN:
                # Someone distant who is opening up.
                return self._build(
                    signal_type="ruptura_de_patron",
                    intensity=0.55,
                    decision_action=decision_action,
                )
            if emotion in _COLD_EMOTIONS and warm_ratio >= BASELINE_WARM_RATIO_COOL:
                # Someone warm who is cooling off.
                return self._build(
                    signal_type="ruptura_de_patron",
                    intensity=0.55,
                    decision_action=decision_action,
                )

        return self._no_signal(decision_action)

    # --- internals -----------------------------------------------------------

    @staticmethod
    def _comprehension_dict(
        comp: dict[str, Any] | Comprehension | None,
    ) -> dict[str, Any] | None:
        if comp is None:
            return None
        if isinstance(comp, Comprehension):
            return comp.model_dump()
        if isinstance(comp, dict):
            return comp
        return None

    @staticmethod
    def _get(comp: dict[str, Any], key: str) -> Any:
        value = comp.get(key)
        if isinstance(value, str):
            return value.strip().lower() or None
        return value

    @staticmethod
    def _topics(comp: dict[str, Any]) -> set[str]:
        raw = comp.get("topics")
        if not isinstance(raw, list):
            return set()
        return {str(t).strip().lower() for t in raw if str(t).strip()}

    def _baseline_warm_ratio(
        self, baseline: list[dict[str, Any]] | None,
    ) -> float | None:
        """Fraction of baseline turns with a warm emotion, or None below min.

        Dicts without an ``emotion`` key are ignored. Returns None when the
        baseline is empty or below ``min_baseline_turns`` — under the minimum,
        ``ruptura_de_patron`` emits no signal (no noise in new chats).
        """
        if not baseline:
            return None
        emotions = [d.get("emotion") for d in baseline if isinstance(d, dict)]
        emotions = [str(e).strip().lower() for e in emotions if isinstance(e, str)]
        if len(emotions) < self.min_baseline_turns:
            return None
        warm = sum(1 for e in emotions if e in _WARM_EMOTIONS)
        return warm / len(emotions)

    def _build(
        self,
        *,
        signal_type: SignalType,
        intensity: float,
        decision_action: str | None,
    ) -> EmotionalSignalRecord:
        return EmotionalSignalRecord(
            signal_detected=True,
            signal_type=signal_type,
            intensity=intensity,
            should_trigger_synthesis=intensity >= self.synthesis_threshold,
            should_escalate_to_owner=intensity >= self.escalate_threshold,
            pipeline_would_have_escalated=(
                True if decision_action == "escalate"
                else (False if decision_action is not None else None)
            ),
        )

    def _no_signal(self, decision_action: str | None) -> EmotionalSignalRecord:
        return EmotionalSignalRecord(
            signal_detected=False,
            signal_type=None,
            intensity=0.0,
            should_trigger_synthesis=False,
            should_escalate_to_owner=False,
            pipeline_would_have_escalated=(
                True if decision_action == "escalate"
                else (False if decision_action is not None else None)
            ),
        )


__all__ = [
    "BASELINE_WARM_RATIO_COOL",
    "BASELINE_WARM_RATIO_OPEN",
    "ESCALATE_THRESHOLD",
    "MIN_BASELINE_TURNS",
    "SYNTHESIS_THRESHOLD",
    "EmotionalSignalDetector",
]
