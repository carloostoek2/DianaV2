"""Boot hydrate of the Fase 2/3 thresholds from system_config."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from diana.application.mood_engine import MoodEngine
from diana.application.turn_classifier import TurnClassifier
from diana.composition import load_runtime_thresholds


class _FakeStore:
    """Store stub recording every get() call for the no-op/I-O assertions."""

    def __init__(
        self,
        *,
        phatic_cfg: dict[str, Any] | None = None,
        mood_cfg: dict[str, Any] | None = None,
    ) -> None:
        self._phatic = phatic_cfg
        self._mood = mood_cfg
        self.get_called_keys: list[str] = []

    async def get(self, key: str) -> Any | None:
        self.get_called_keys.append(key)
        if key == "phatic_classifier":
            return self._phatic
        if key == "mood_engine":
            return self._mood
        return None

    async def get_autonomous_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_supervised_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_eval_thresholds(self) -> dict[str, Any]:
        return {}


class _BoomStore:
    """Store whose get() raises (transient DB error) on every key."""

    async def get(self, key: str) -> Any | None:
        raise RuntimeError("transient db failure")

    async def get_autonomous_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_supervised_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_eval_thresholds(self) -> dict[str, Any]:
        return {}


def _app(
    *,
    classifier: object | None,
    mood: object | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        emotional_detector=None,
        profile_synthesis_trigger=None,
        profile_synthesis_service=None,
        turn_classifier=classifier,
        mood_engine=mood,
    )


@pytest.mark.asyncio
async def test_load_runtime_thresholds_applies_classifier_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classifier = TurnClassifier(confidence_min=0.7)
    mood = MoodEngine()
    app = _app(classifier=classifier, mood=mood)
    fake = _FakeStore(phatic_cfg={"confidence_min": 0.9})
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert classifier._confidence_min == 0.9  # noqa: SLF001
    # The mood override is untouched (no mood_engine config key).
    assert mood.return_rate == pytest.approx(0.05)
    assert "phatic_classifier" in fake.get_called_keys


@pytest.mark.asyncio
async def test_load_runtime_thresholds_applies_mood_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classifier = TurnClassifier(confidence_min=0.7)
    mood = MoodEngine()
    app = _app(classifier=classifier, mood=mood)
    fake = _FakeStore(mood_cfg={"return_rate": 0.2, "signal_weight": 0.6, "noise": 0.1})
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert mood.return_rate == pytest.approx(0.2)
    assert mood.signal_weight == pytest.approx(0.6)
    assert mood.noise == pytest.approx(0.1)
    # The classifier override is untouched (no phatic_classifier config key).
    assert classifier._confidence_min == 0.7  # noqa: SLF001
    assert "mood_engine" in fake.get_called_keys


@pytest.mark.asyncio
async def test_load_runtime_thresholds_axis_weights_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mood = MoodEngine()
    app = _app(classifier=None, mood=mood)
    fake = _FakeStore(mood_cfg={"axis_weights": {"warm": 2.0}})
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert mood.axis_weights["warm"] == pytest.approx(2.0)
    assert mood.axis_weights["playful"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_load_runtime_thresholds_wired_none_noop_no_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classifier/mood None (flag off) → no DB read, no override (no-op, no I/O)."""
    app = _app(classifier=None, mood=None)
    fake = _FakeStore(phatic_cfg={"confidence_min": 0.9})
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert fake.get_called_keys == []


@pytest.mark.asyncio
async def test_load_runtime_thresholds_db_error_does_not_break_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient DB error on the classifier/mood read must not break boot."""
    classifier = TurnClassifier(confidence_min=0.7)
    mood = MoodEngine()
    app = _app(classifier=classifier, mood=mood)
    monkeypatch.setattr(
        "diana.composition.SqlSystemConfigStore", lambda _sf: _BoomStore()
    )
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    # Boot survived; thresholds keep their defaults.
    assert classifier._confidence_min == 0.7  # noqa: SLF001
    assert mood.return_rate == pytest.approx(0.05)
