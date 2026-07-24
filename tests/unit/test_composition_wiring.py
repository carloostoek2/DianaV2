"""Regression: composition root must wire status_sink as an object with .transition."""

from __future__ import annotations

from pathlib import Path

import pytest

import diana


@pytest.fixture
def _comp_src() -> str:
    root = Path(diana.__file__).resolve().parent
    return (root / "composition.py").read_text(encoding="utf-8")


def test_composition_status_sink_is_coordinator_not_method(_comp_src: str) -> None:
    """Director expects TurnStatusSink.transition; a method object has no .transition."""
    assert "status_sink=coordinator.transition_sink" not in _comp_src
    assert "status_sink=coordinator" in _comp_src


def test_composition_gray_zone_wired_to_orchestrator(_comp_src: str) -> None:
    """Orchestrator receives gray_zone and feature_gray_zone_enabled."""
    assert "gray_zone=gray_zone" in _comp_src
    assert "feature_gray_zone_enabled=feature_gray_zone_enabled" in _comp_src


def test_composition_gray_zone_service_conditional(_comp_src: str) -> None:
    """GrayZoneService is only created when feature_gray_zone_enabled is True."""
    assert "if feature_gray_zone_enabled:" in _comp_src
    assert "gray_zone = GrayZoneService(" in _comp_src


def test_composition_decider_receives_feature_flag(_comp_src: str) -> None:
    """Decider is wired with feature_gray_zone_enabled."""
    assert "Decider(feature_gray_zone_enabled=feature_gray_zone_enabled)" in _comp_src


def test_composition_load_feature_flags_removed(_comp_src: str) -> None:
    """load_feature_flags was removed per BUG-1 (option b)."""
    assert "def load_feature_flags" not in _comp_src
