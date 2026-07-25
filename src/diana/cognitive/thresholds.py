"""F3 dual evaluation threshold defaults (SPEC-FASE3 §4.2).

Pure constants for autonomous vs supervised modes.

**Key-schema landmine (item 2 handoff):** F1 ``eval_thresholds`` uses the
single key ``safety`` (default 0.3). F3 dual thresholds use only
``safety_min``, ``doctrine_min``, and ``naturalness_min``. Do **not** mix
shapes when wiring Decider — map explicitly per mode.

Callers apply these defaults when DB/store values are missing; store
readers must not fall back here (A4: empty dict when absent).

Values are frozen via ``MappingProxyType`` so shared defaults cannot be
mutated in place.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

DEFAULT_AUTONOMOUS_THRESHOLDS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "safety_min": 0.9,
        "doctrine_min": 0.8,
        "naturalness_min": 0.7,
    }
)

DEFAULT_SUPERVISED_THRESHOLDS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "safety_min": 0.5,
        "doctrine_min": 0.4,
        "naturalness_min": 0.5,
    }
)

__all__ = [
    "DEFAULT_AUTONOMOUS_THRESHOLDS",
    "DEFAULT_SUPERVISED_THRESHOLDS",
]
