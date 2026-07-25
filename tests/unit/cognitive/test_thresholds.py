"""Unit tests for F3 dual threshold defaults (SPEC-FASE3 §4.2)."""

from __future__ import annotations

import pytest


def test_default_autonomous_and_supervised_thresholds_match_spec() -> None:
    from diana.cognitive.thresholds import (
        DEFAULT_AUTONOMOUS_THRESHOLDS,
        DEFAULT_SUPERVISED_THRESHOLDS,
    )

    assert dict(DEFAULT_AUTONOMOUS_THRESHOLDS) == {
        "safety_min": 0.9,
        "doctrine_min": 0.8,
        "naturalness_min": 0.7,
    }
    assert dict(DEFAULT_SUPERVISED_THRESHOLDS) == {
        "safety_min": 0.5,
        "doctrine_min": 0.4,
        "naturalness_min": 0.5,
    }


def test_default_threshold_keys_are_only_star_min() -> None:
    """F3 keys are *_min only — never F1 bare ``safety`` (item 2 landmine)."""
    from diana.cognitive.thresholds import (
        DEFAULT_AUTONOMOUS_THRESHOLDS,
        DEFAULT_SUPERVISED_THRESHOLDS,
    )

    expected = {"safety_min", "doctrine_min", "naturalness_min"}
    assert set(DEFAULT_AUTONOMOUS_THRESHOLDS) == expected
    assert set(DEFAULT_SUPERVISED_THRESHOLDS) == expected
    assert "safety" not in DEFAULT_AUTONOMOUS_THRESHOLDS
    assert "safety" not in DEFAULT_SUPERVISED_THRESHOLDS


def test_default_threshold_mappings_are_immutable() -> None:
    from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS

    with pytest.raises(TypeError):
        DEFAULT_AUTONOMOUS_THRESHOLDS["safety_min"] = 0.0  # type: ignore[index]
