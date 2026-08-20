"""TurnClassifier — pure turn classification (Fase 2, shadow), no LLM.

Classifies each VIP turn into ``fatico | informativo | emocional | sensible``
with a pure heuristic over the **analyst comprehension** (intent / emotion /
urgency / risk / topics — already paid for by the pipeline) plus the raw
``incoming.text``. No extra LLM call per turn.

"no estoy seguro" is expressed as ``confidence < confidence_min`` (never
fast-lane). EA-03: ``sensitive`` is a hard rule and is never fático.

Fase 2/3 shadow — no LLM, reusa la comprehension del analyst; constantes fijas
con override manual, nunca auto-calibradas. Pure application module: imports
only ``cognitive.models`` + stdlib (no chat-framework or persistence imports).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from diana.cognitive.models import Comprehension, TurnCategory
from diana.cognitive.template_gate import looks_like_pure_greeting_text

logger = logging.getLogger("diana.application")

# Fixed threshold (constant, never auto-calibrated). Manual override only.
CLASSIFIER_CONFIDENCE_MIN = 0.7

# Closed analyst catalog (analyst.py ``_SYSTEM``) — NEVER free strings.
_PHATIC_INTENTS = frozenset({"saludar", "despedirse", "agradecer"})
_INFORMATIONAL_INTENTS = frozenset(
    {
        "preguntar_actividad",
        "recordar_evento",
        "solicitar_contenido",
        "consultar_politica",
        "confirmar_entrega",
        "dar_feedback",
    }
)
_EMOTIONAL_INTENTS = frozenset(
    {
        "queja",
        "pedir_consejo",
        "contar_anecdota",
        "flirtear",
        "compartir_logro",
    }
)
_NEGATIVE_EMOTIONS = frozenset({"ansiosa", "molesta", "triste"})
_SENSITIVE_EMOTIONS = frozenset({"molesta", "triste"})
_NEUTRAL_POSITIVE = frozenset({"neutral", "positiva"})
_EMOTIONAL_TOPICS = frozenset({"tema_pesado", "duelo"})

# Text cues for the "no estoy seguro" ambiguity check. The check runs ONLY in
# the phatic branch (intent already confirmed), so the phatic condition is
# established by the branch — an emotional-text term alone makes the turn
# ambiguous (review round 1, S2). Covers saludar/agradecer/despedirse alike.
_EMOTIONAL_TEXT_TERMS = (
    "no sé",
    "contarte",
    "preocup",
    "siento",
    "miedo",
    "quise",
    "pasa que",
    "molesta",
    "triste",
)


@dataclass(frozen=True, slots=True)
class TurnClassification:
    """One turn classified by :class:`TurnClassifier`.

    ``category`` is ALWAYS one of the 4 CHECK values (never "no_estoy_seguro");
    the uncertainty mode is ``confidence < confidence_min`` (``is_confident``).
    """

    category: TurnCategory
    confidence: float
    reason: str


class TurnClassifier:
    """Pure heuristic classifier over the analyst comprehension + text."""

    def __init__(self, confidence_min: float = CLASSIFIER_CONFIDENCE_MIN) -> None:
        # Clamp to [0, 1] so a typo'd constructor arg cannot invert the gate.
        self._confidence_min = min(max(float(confidence_min), 0.0), 1.0)

    @property
    def confidence_min(self) -> float:
        return self._confidence_min

    def apply_overrides(self, config: dict[str, Any]) -> None:
        """Manual threshold override from ``system_config`` (key ``phatic_classifier``).

        This is the ONLY override point — thresholds are never auto-calibrated.
        Missing keys are ignored; invalid values are rejected without crashing.
        """
        if not isinstance(config, dict):
            return
        try:
            raw = config.get("confidence_min")
            if raw is not None:
                value = float(raw)
                if 0.0 <= value <= 1.0:
                    self._confidence_min = value
        except (TypeError, ValueError):
            pass

    def is_confident(self, classification: TurnClassification) -> bool:
        """True when the classification is safe to fast-lane (no ambiguity)."""
        return classification.confidence >= self._confidence_min

    def classify(
        self,
        text: str,
        comprehension: dict[str, Any] | Comprehension | None,
    ) -> TurnClassification:
        """Classify the turn. Category priority: sensitive > emotional >
        informational > phatic > safe fallback (EA-03 hard rule first)."""
        comp = self._comprehension_dict(comprehension)
        if comp is None:
            return TurnClassification("fatico", 0.3, "sin_comprehension")

        emotion = self._get(comp, "emotion")
        urgency = self._get(comp, "urgency")
        risk = self._get(comp, "risk")
        intent = self._get(comp, "intent")
        topics = self._topics(comp)

        # 1. sensitive (EA-03 hard rule — never fast-lane).
        if risk == "alto" or (
            emotion in _SENSITIVE_EMOTIONS and risk in {"medio", "alto"}
        ):
            return TurnClassification("sensible", 1.0, "riesgo_alto_o_emotion_negativa")

        # 2. emotional.
        if emotion in _NEGATIVE_EMOTIONS or urgency == "alta" or risk == "medio":
            return TurnClassification("emocional", 0.9, "emotion_negativa_o_urgency_alta")
        if intent in _EMOTIONAL_INTENTS:
            return TurnClassification("emocional", 0.85, "intent_con_carga")
        if bool(topics & _EMOTIONAL_TOPICS):
            return TurnClassification("emocional", 0.8, "topics_pesados")

        # 3. informational.
        if (
            intent in _INFORMATIONAL_INTENTS
            and emotion in _NEUTRAL_POSITIVE
            and urgency == "baja"
            and risk == "bajo"
        ):
            return TurnClassification("informativo", 0.9, "intent_informativo")

        # 4. phatic candidate (saludos / small talk).
        if (
            intent in _PHATIC_INTENTS
            and emotion in (_NEUTRAL_POSITIVE | {"cariñosa"})
            and urgency == "baja"
            and risk == "bajo"
        ):
            confidence = 1.0
            reason = "saludo_sin_carga"
            if emotion == "cariñosa":
                confidence = 0.7
                reason = "saludo_con_afecto"
            if self._text_ambiguous(text):
                confidence = 0.3
                reason = "ambiguedad_saludo_mas_carga"  # modo "no estoy seguro"
            elif text is None or len(text.strip()) <= 2:
                confidence = min(confidence, 0.5)
                reason = "texto_muy_corto"
            return TurnClassification(
                "fatico", max(0.0, min(1.0, confidence)), reason
            )

        # 5. fallback — informational (safe, never fast-lane).
        return TurnClassification("informativo", 0.5, "fallback_no_clasificado")

    # --- internals (shape copied from emotional_signal_detector) ---------------

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
        topics: set[str] = set()
        for t in raw:
            if not isinstance(t, str):
                continue
            token = t.strip().lower()
            if token:
                topics.add(token)
        return topics

    @staticmethod
    def _text_ambiguous(text: str) -> bool:
        """Phatic turn whose TEXT also carries emotional load → "no estoy seguro".

        Called ONLY inside the phatic branch (intent already confirmed as
        ``saludar`` / ``agradecer`` / ``despedirse``), so the phatic condition is
        already established by the branch. Any emotional-text term therefore
        signals a mixed message (e.g. "qué haces... es que no sé si contarte
        algo" or "gracias... es que no sé si contarte algo") and the turn is
        pulled out of the fast-lane (review round 1: S2 — the check used to
        require a greeting term, leaving ``agradecer``/``despedirse`` turns with
        emotional load at fático 1.0). Empty/None text is never ambiguous
        (falls to the short-text branch).
        """
        if not text:
            return False
        lower = text.lower()
        return any(t in lower for t in _EMOTIONAL_TEXT_TERMS)


def is_pure_greeting(
    text: str,
    comprehension: dict[str, Any] | Comprehension | None,
    *,
    classifier: TurnClassifier,
) -> bool:
    """True when Director may cut after Analyst for pure VIP saludo.

    Contract (PLAN A1 + 2026-08-17 lock): intent == ``saludar`` AND the raw
    text looks like a short greeting (keyword + ≤4 words) AND TurnClassifier
    category is ``fatico`` AND ``is_confident``. Fail open (False) otherwise.
    Thanks/goodbye phatic intents are excluded by the saludar gate.
    """
    if isinstance(comprehension, Comprehension):
        raw_intent = comprehension.intent
    elif isinstance(comprehension, dict):
        raw_intent = comprehension.get("intent")
    else:
        return False
    intent = str(raw_intent).strip().lower() if raw_intent is not None else ""
    if intent != "saludar":
        return False
    if not looks_like_pure_greeting_text(text):
        return False
    classification = classifier.classify(text, comprehension)
    return (
        classification.category == "fatico"
        and classifier.is_confident(classification)
    )


def make_pure_greeting_cut(
    classifier: TurnClassifier,
) -> Callable[[str, dict[str, Any] | Comprehension | None], bool]:
    """Bind a TurnClassifier into a Director-injectable pure-greeting predicate."""

    def _cut(
        text: str,
        comprehension: dict[str, Any] | Comprehension | None,
    ) -> bool:
        return is_pure_greeting(text, comprehension, classifier=classifier)

    return _cut


__all__ = [
    "CLASSIFIER_CONFIDENCE_MIN",
    "TurnClassification",
    "TurnClassifier",
    "is_pure_greeting",
    "make_pure_greeting_cut",
]
