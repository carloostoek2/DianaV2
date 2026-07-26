"""RuntimeThresholds — shared mutable holder for live Decider mins."""

from __future__ import annotations

from diana.application.runtime_thresholds import RuntimeThresholds
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS


def test_defaults_match_autonomous_constants() -> None:
    rt = RuntimeThresholds()
    assert rt.autonomous["safety_min"] == DEFAULT_AUTONOMOUS_THRESHOLDS["safety_min"]
    assert rt.autonomous["doctrine_min"] == DEFAULT_AUTONOMOUS_THRESHOLDS["doctrine_min"]
    assert rt.autonomous["naturalness_min"] == DEFAULT_AUTONOMOUS_THRESHOLDS["naturalness_min"]
    assert rt.safety == 0.3


def test_replace_autonomous_updates_mapping() -> None:
    rt = RuntimeThresholds()
    rt.replace_autonomous(
        {"safety_min": 0.55, "doctrine_min": 0.44, "naturalness_min": 0.33}
    )
    assert rt.autonomous["safety_min"] == 0.55
    assert rt.autonomous["doctrine_min"] == 0.44
    assert rt.autonomous["naturalness_min"] == 0.33


def test_partial_replace_merges_over_defaults() -> None:
    rt = RuntimeThresholds()
    rt.replace_autonomous({"safety_min": 0.11})
    assert rt.autonomous["safety_min"] == 0.11
    assert rt.autonomous["doctrine_min"] == DEFAULT_AUTONOMOUS_THRESHOLDS["doctrine_min"]


def test_autonomous_property_is_snapshot_not_live_mut_alias() -> None:
    rt = RuntimeThresholds()
    snap = rt.autonomous
    # Mutating the returned mapping must not corrupt the holder.
    if isinstance(snap, dict):
        snap["safety_min"] = 0.01
    assert rt.autonomous["safety_min"] == DEFAULT_AUTONOMOUS_THRESHOLDS["safety_min"]
