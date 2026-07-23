"""Regression: composition root must wire status_sink as an object with .transition."""

from __future__ import annotations

from pathlib import Path

import diana


def test_composition_status_sink_is_coordinator_not_method() -> None:
    """Director expects TurnStatusSink.transition; a method object has no .transition."""
    root = Path(diana.__file__).resolve().parent
    src = (root / "composition.py").read_text(encoding="utf-8")
    assert "status_sink=coordinator.transition_sink" not in src
    assert "status_sink=coordinator" in src
