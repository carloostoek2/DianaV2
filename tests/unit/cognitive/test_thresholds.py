"""Unit tests for F3 dual threshold defaults (SPEC-FASE3 §4.2)."""

from __future__ import annotations


def test_default_autonomous_and_supervised_thresholds_match_spec() -> None:
    from diana.cognitive.thresholds import (
        DEFAULT_AUTONOMOUS_THRESHOLDS,
        DEFAULT_SUPERVISED_THRESHOLDS,
    )

    assert DEFAULT_AUTONOMOUS_THRESHOLDS == {
        "safety_min": 0.9,
        "doctrine_min": 0.8,
        "naturalness_min": 0.7,
    }
    assert DEFAULT_SUPERVISED_THRESHOLDS == {
        "safety_min": 0.5,
        "doctrine_min": 0.4,
        "naturalness_min": 0.5,
    }
    assert set(DEFAULT_AUTONOMOUS_THRESHOLDS) == {
        "safety_min",
        "doctrine_min",
        "naturalness_min",
    }
    assert set(DEFAULT_SUPERVISED_THRESHOLDS) == {
        "safety_min",
        "doctrine_min",
        "naturalness_min",
    }
