"""Deterministic correction-severity prefill (SPEC-EA-07) — pure module."""

from __future__ import annotations

from diana.application.severity_prefill import (
    DEFAULT_SEVERITY,
    SEVERITY_LEVELS,
    preselect_severity,
)
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS


def test_constant_shape() -> None:
    assert SEVERITY_LEVELS == ("minor", "moderate", "major")
    assert DEFAULT_SEVERITY == "moderate"


def test_gray_zone_open_is_major() -> None:
    assert preselect_severity(gray_zone_open=True) == "major"


def test_doctrine_below_min_is_major() -> None:
    assert preselect_severity(doctrine=0.5) == "major"


def test_safety_below_min_is_major() -> None:
    assert preselect_severity(safety=0.5) == "major"


def test_hard_gate_is_major() -> None:
    assert preselect_severity(hard_gate=True) == "major"


def test_default_no_signals_is_moderate() -> None:
    assert preselect_severity() == "moderate"


def test_doctrine_boundary_is_not_major() -> None:
    """doctrine == doctrine_min (0.8) does NOT trip major (strict <)."""
    assert (
        preselect_severity(
            doctrine=DEFAULT_AUTONOMOUS_THRESHOLDS["doctrine_min"]
        )
        == "moderate"
    )


def test_safety_boundary_is_not_major() -> None:
    assert (
        preselect_severity(
            safety=DEFAULT_AUTONOMOUS_THRESHOLDS["safety_min"]
        )
        == "moderate"
    )


def test_none_signal_is_not_major() -> None:
    assert preselect_severity(doctrine=None, safety=None) == "moderate"


def test_non_numeric_signals_fall_back_to_moderate() -> None:
    """Review round 1 (FIX 5): non-numeric dims (string/None/bool) are treated
    as absent — no TypeError, and the prefill falls back to moderate instead of
    guessing a severity from a malformed trace row."""
    assert preselect_severity(doctrine="low", safety="high") == "moderate"
    assert preselect_severity(doctrine=None, safety="n/a") == "moderate"
    assert preselect_severity(doctrine=True, safety=False) == "moderate"
    # A bool must NOT be treated as numeric: as-numeric, False == 0 < doctrine_min
    # would fire major; the guard treats it as absent → moderate.
    assert preselect_severity(doctrine=False) == "moderate"
    assert preselect_severity(safety=False) == "moderate"
    # A numeric low doctrine still fires major while the string safety is ignored.
    assert preselect_severity(doctrine=0.5, safety="nope") == "major"


def test_never_returns_minor() -> None:
    """Minor is human-only: the system never presumes a downgrade."""
    cases = [
        {},
        {"gray_zone_open": True},
        {"doctrine": 0.0},
        {"safety": 0.0},
        {"hard_gate": True},
        {"gray_zone_open": True, "doctrine": 0.5, "safety": 0.5, "hard_gate": True},
    ]
    for kwargs in cases:
        assert preselect_severity(**kwargs) != "minor"
