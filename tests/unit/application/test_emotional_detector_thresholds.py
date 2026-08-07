"""Boot hydrate of the emotional detector thresholds from system_config."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from diana.application.emotional_signal_detector import (
    ESCALATE_THRESHOLD,
    MIN_BASELINE_TURNS,
    SYNTHESIS_THRESHOLD,
    EmotionalSignalDetector,
)
from diana.composition import load_runtime_thresholds


class _FakeStore:
    def __init__(self, *, detector_cfg: dict[str, Any] | None = None) -> None:
        self._detector = detector_cfg

    async def get(self, key: str) -> Any | None:
        if key == "emotional_detector":
            return self._detector
        return None

    async def get_autonomous_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_supervised_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_eval_thresholds(self) -> dict[str, Any]:
        return {}


@pytest.mark.asyncio
async def test_load_runtime_thresholds_applies_detector_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = EmotionalSignalDetector()
    assert detector.synthesis_threshold == SYNTHESIS_THRESHOLD
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        emotional_detector=detector,
    )
    fake = _FakeStore(
        detector_cfg={
            "synthesis_threshold": 0.6,
            "escalate_threshold": 0.9,
            "min_baseline_turns": 3,
        }
    )
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert detector.synthesis_threshold == 0.6
    assert detector.escalate_threshold == 0.9
    assert detector.min_baseline_turns == 3


@pytest.mark.asyncio
async def test_load_runtime_thresholds_no_key_keeps_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = EmotionalSignalDetector()
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        emotional_detector=detector,
    )
    fake = _FakeStore(detector_cfg=None)
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert detector.synthesis_threshold == SYNTHESIS_THRESHOLD
    assert detector.escalate_threshold == ESCALATE_THRESHOLD
    assert detector.min_baseline_turns == MIN_BASELINE_TURNS


@pytest.mark.asyncio
async def test_load_runtime_thresholds_detector_none_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        emotional_detector=None,
    )
    fake = _FakeStore(detector_cfg={"synthesis_threshold": 0.6})
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    # no-op: nothing to override, nothing raised
