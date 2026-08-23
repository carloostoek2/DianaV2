"""Reaction signal H2 (C3) — deterministic VIP follow-up classification, no LLM.

SPEC-AUTONOMIA-CALIBRACION.md §6 (C3): when a message is delivered, the VIP's
reaction qualifies the result:

- positive → refuerza confianza · negative/molesta → resta (asimetría)
  · silence → neutral/leve negativo · neutral → sin cambio.

The classifier reuses the ANALYST emotion (already computed, no extra LLM
call) plus a fixed polarity lexicon over the follow-up text. Pure module:
stdlib only.

Constants are fixed with a manual ``apply_overrides`` (``system_config`` key
``reaction_signal``) — never auto-calibrated.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger("diana.application")

__all__ = [
    "DEFAULT_POSITIVE_LEXICON",
    "DEFAULT_NEGATIVE_LEXICON",
    "ReactionSignal",
    "ReactionSignalClassifier",
    "classify",
]

ReactionSignal = Literal["positive", "neutral", "negative"]

DEFAULT_POSITIVE_LEXICON: tuple[str, ...] = (
    "gracias",
    "genial",
    "perfecto",
    "excelente",
    "me encanta",
    "me alegra",
    "súper",
    "buenísimo",
    "👍",
    "😊",
    "😁",
    "❤",
    "claro",
    "dale",
    "ok",
    "está bien",
    "me gusta",
)

DEFAULT_NEGATIVE_LEXICON: tuple[str, ...] = (
    "no me gusta",
    "mal",
    "problema",
    "molesta",
    "enojada",
    "enojado",
    "feo",
    "triste",
    "no quiero",
    "no sirve",
    "pésimo",
    "queja",
    "demora",
    "lento",
    "nunca respondes",
    "siempre igual",
    "😠",
    "😡",
    "😢",
    "😞",
    "horrible",
    "peor",
)

# Analyst emotions that are strongly negative/positive (deterministic).
_NEGATIVE_EMOTIONS = frozenset({"molesta", "triste", "ansiosa"})
_POSITIVE_EMOTIONS = frozenset({"positiva", "cariñosa"})


def classify(
    text: str | None,
    comprehension: dict[str, Any] | None,
    *,
    positive_lexicon: tuple[str, ...] = DEFAULT_POSITIVE_LEXICON,
    negative_lexicon: tuple[str, ...] = DEFAULT_NEGATIVE_LEXICON,
) -> ReactionSignal:
    """Classify the VIP's follow-up reaction (positive/neutral/negative).

    Emotion wins (analyst signal is stronger than surface tokens); the lexicon
    breaks ties / covers the no-emotion case. Empty text + no comprehension →
    neutral (the caller decides "silence" separately).
    """
    emotion = None
    if isinstance(comprehension, dict):
        raw = comprehension.get("emotion")
        if isinstance(raw, str):
            emotion = raw.strip().lower()

    if emotion in _NEGATIVE_EMOTIONS:
        return "negative"
    if emotion in _POSITIVE_EMOTIONS:
        return "positive"

    lower = (text or "").strip().lower()
    if not lower:
        return "neutral"

    # Count with removal so overlapping tokens never double-count: "no me
    # gusta" must not ALSO match the positive "me gusta" substring.
    work = lower
    negative = 0
    for token in negative_lexicon:
        while token and token in work:
            negative += 1
            work = work.replace(token, " ", 1)
    positive = 0
    for token in positive_lexicon:
        while token and token in work:
            positive += 1
            work = work.replace(token, " ", 1)
    if negative > positive:
        return "negative"
    if positive > negative:
        return "positive"
    return "neutral"


class ReactionSignalClassifier:
    """Callable C3 classifier with manual ``system_config`` overrides."""

    def __init__(
        self,
        *,
        positive_lexicon: tuple[str, ...] = DEFAULT_POSITIVE_LEXICON,
        negative_lexicon: tuple[str, ...] = DEFAULT_NEGATIVE_LEXICON,
    ) -> None:
        self._positive = list(positive_lexicon)
        self._negative = list(negative_lexicon)

    def __call__(
        self, text: str | None, comprehension: dict[str, Any] | None
    ) -> ReactionSignal:
        return classify(
            text,
            comprehension,
            positive_lexicon=tuple(self._positive),
            negative_lexicon=tuple(self._negative),
        )

    def apply_overrides(self, config: dict[str, Any]) -> None:
        """Manual override from ``system_config`` (key ``reaction_signal``)."""
        if not isinstance(config, dict):
            return
        raw_positive = config.get("positive_lexicon")
        if isinstance(raw_positive, list):
            self._positive = [str(t) for t in raw_positive if str(t).strip()]
        raw_negative = config.get("negative_lexicon")
        if isinstance(raw_negative, list):
            self._negative = [str(t) for t in raw_negative if str(t).strip()]
