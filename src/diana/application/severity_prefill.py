"""Deterministic correction-severity prefill (SPEC-EA-07, UI).

Pure module: stdlib + ``cognitive.thresholds`` only (no aiogram, no LLM, no DB).

``preselect_severity`` turns the prefill signals into a default severity for
the owner's correction picker. It NEVER returns "minor" — minor is a human-only
downgrade; the owner actively lowers severity, the system never presumes it.

Signals (Fase 4):
- C: a gray-zone query is open for the turn → major.
- A: the shadow evaluation has doctrine/safety below the SAME autonomous mins
  that already gate auto-send (``DEFAULT_AUTONOMOUS_THRESHOLDS``) → major.
- B: the draft trips the SEGURIDAD hard gate (forbidden keyword / PII) → major.
- default → moderate (today's behavior; byte-identical with the classic -0.20).
"""

from __future__ import annotations

from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS

SEVERITY_LEVELS: tuple[str, ...] = ("minor", "moderate", "major")
DEFAULT_SEVERITY = "moderate"

__all__ = [
    "DEFAULT_SEVERITY",
    "SEVERITY_LEVELS",
    "preselect_severity",
]


def preselect_severity(
    *,
    gray_zone_open: bool = False,
    doctrine: float | None = None,
    safety: float | None = None,
    hard_gate: bool = False,
) -> str:
    """Deterministic default severity for the owner correction picker.

    Returns ``"major"`` when any strong signal fires (open gray-zone query,
    hard gate, or doctrine/safety below the autonomous mins), otherwise
    ``"moderate"``. Never returns ``"minor"`` — only the owner can downgrade.
    """
    if gray_zone_open or hard_gate:
        return "major"
    doctrine_min = DEFAULT_AUTONOMOUS_THRESHOLDS["doctrine_min"]
    safety_min = DEFAULT_AUTONOMOUS_THRESHOLDS["safety_min"]
    if doctrine is not None and doctrine < doctrine_min:
        return "major"
    if safety is not None and safety < safety_min:
        return "major"
    return "moderate"
