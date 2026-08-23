"""Coincidence engine (C1) — pure shadow-verdict × owner-outcome comparison.

SPEC-AUTONOMIA-CALIBRACION.md §5 C1: compare, per finished turn, what the
shadow simulation (Decider with autonomy ON) would have done against what the
owner actually did, and label the result:

| simulación dijo          | dueña hizo                        | etiqueta     |
|--------------------------|-----------------------------------|--------------|
| ✅ habría enviado (send) | aprobó sin cambios (approved_as_is)| acierto      |
| ✅ habría enviado (send) | corrigió o escaló (corrected/escalated)| desacuerdo|
| ❌ no habría enviado     | aprobó (approved_as_is)           | conservadora |

Anything else (no owner outcome yet, or both sides agreed NOT to send) is
``None`` — it is not a match-rate event. The match rate is defined as
``aciertos / (aciertos + desacuerdos)`` (spec §5); ``conservadora`` is excluded
from both numerator and denominator.

Pure module: stdlib only, no LLM, no persistence, no aiogram.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

__all__ = [
    "SHADOW_VERDICTS",
    "OWNER_OUTCOMES",
    "CoincidenceLabel",
    "label",
    "match_rate",
]

# Closed vocabularies (mirror the turn_outcome_log CheckConstraints).
SHADOW_VERDICTS: tuple[str, ...] = ("send", "blocked", "escalate", "doctrine")
OWNER_OUTCOMES: tuple[str, ...] = ("approved_as_is", "corrected", "escalated")

CoincidenceLabel = Literal["acierto", "desacuerdo", "conservadora"]


def _norm(value: object) -> str:
    """Normalize a vocabulary token: strip + lowercase + empty-safe."""
    return str(value or "").strip().lower()


def label(shadow_verdict: str | None, owner_outcome: str | None) -> CoincidenceLabel | None:
    """Classify one finished turn per the §5 table.

    Returns ``None`` when the pair is not a match-rate event: missing owner
    outcome (turn still open), or a non-send verdict combined with a
    corrected/escalated outcome (both sides agreed not to send — informative
    but not part of the coincidence rate).
    """
    verdict = _norm(shadow_verdict)
    outcome = _norm(owner_outcome)

    if verdict == "send":
        if outcome == "approved_as_is":
            return "acierto"
        if outcome in ("corrected", "escalated"):
            return "desacuerdo"
        return None  # no owner outcome yet (or unknown) → no event

    if verdict in ("blocked", "escalate", "doctrine"):
        if outcome == "approved_as_is":
            return "conservadora"
        return None  # non-send + corrected/escalated → agreement NOT to send

    return None  # unknown verdict → no event


def match_rate(labels: Iterable[CoincidenceLabel | None]) -> float | None:
    """Coincidence rate = aciertos / (aciertos + desacuerdos).

    Returns ``None`` when the denominator is zero (not enough data to judge).
    ``conservadora`` and ``None`` labels are ignored.
    """
    aciertos = 0
    desacuerdos = 0
    for item in labels:
        if item == "acierto":
            aciertos += 1
        elif item == "desacuerdo":
            desacuerdos += 1
    denominator = aciertos + desacuerdos
    if denominator == 0:
        return None
    return aciertos / denominator
