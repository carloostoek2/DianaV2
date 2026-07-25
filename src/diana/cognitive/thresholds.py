"""F3 dual evaluation threshold defaults (SPEC-FASE3 §4.2).

Pure constants for autonomous vs supervised modes. Keys use ``*_min``
(not F1 ``eval_thresholds.safety``). Callers apply these defaults when
DB/store values are missing; store readers must not fall back here.
"""

from __future__ import annotations

from typing import Final

DEFAULT_AUTONOMOUS_THRESHOLDS: Final[dict[str, float]] = {
    "safety_min": 0.9,
    "doctrine_min": 0.8,
    "naturalness_min": 0.7,
}

DEFAULT_SUPERVISED_THRESHOLDS: Final[dict[str, float]] = {
    "safety_min": 0.5,
    "doctrine_min": 0.4,
    "naturalness_min": 0.5,
}

__all__ = [
    "DEFAULT_AUTONOMOUS_THRESHOLDS",
    "DEFAULT_SUPERVISED_THRESHOLDS",
]
