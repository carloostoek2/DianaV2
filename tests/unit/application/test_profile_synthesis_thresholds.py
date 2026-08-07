"""Boot hydrate of the profile-synthesis thresholds from system_config."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from diana.application.profile_synthesis_service import ProfileSynthesisService
from diana.application.profile_synthesis_trigger_service import (
    ProfileSynthesisTriggerService,
)
from diana.composition import load_runtime_thresholds


class _FakeStore:
    """Store stub recording every get() call for the no-op/I-O assertions."""

    def __init__(self, *, synthesis_cfg: dict[str, Any] | None = None) -> None:
        self._synthesis = synthesis_cfg
        self.get_called_keys: list[str] = []

    async def get(self, key: str) -> Any | None:
        self.get_called_keys.append(key)
        if key == "profile_synthesis":
            return self._synthesis
        return None

    async def get_autonomous_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_supervised_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_eval_thresholds(self) -> dict[str, Any]:
        return {}


class _BoomStore:
    """Store whose get() raises (transient DB error) on the synthesis key."""

    async def get(self, key: str) -> Any | None:
        raise RuntimeError("transient db failure")

    async def get_autonomous_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_supervised_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_eval_thresholds(self) -> dict[str, Any]:
        return {}


def _trigger() -> ProfileSynthesisTriggerService:
    return ProfileSynthesisTriggerService(
        profile_reader=object(),  # type: ignore[arg-type]
        activity=object(),  # type: ignore[arg-type]
        volume_threshold=25,
        inactivity_minutes=30,
    )


def _service() -> ProfileSynthesisService:
    return ProfileSynthesisService(
        llm=object(),  # type: ignore[arg-type]
        profile_store=object(),  # type: ignore[arg-type]
        memories=object(),  # type: ignore[arg-type]
        corrections=object(),  # type: ignore[arg-type]
        confidence_min=0.6,
    )


@pytest.mark.asyncio
async def test_load_runtime_thresholds_applies_synthesis_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger = _trigger()
    service = _service()
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        emotional_detector=None,
        profile_synthesis_trigger=trigger,
        profile_synthesis_service=service,
    )
    fake = _FakeStore(
        synthesis_cfg={"volume_threshold": 40, "confidence_min": 0.7}
    )
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert trigger._volume_threshold == 40  # noqa: SLF001
    assert service._confidence_min == 0.7  # noqa: SLF001


@pytest.mark.asyncio
async def test_load_runtime_thresholds_no_key_keeps_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger = _trigger()
    service = _service()
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        emotional_detector=None,
        profile_synthesis_trigger=trigger,
        profile_synthesis_service=service,
    )
    fake = _FakeStore(synthesis_cfg=None)
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert trigger._volume_threshold == 25  # noqa: SLF001
    assert service._confidence_min == 0.6  # noqa: SLF001


@pytest.mark.asyncio
async def test_load_runtime_thresholds_wired_none_noop_no_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trigger/service None (flag off) → no DB read, no override (no-op, no I/O)."""
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        emotional_detector=None,
        profile_synthesis_trigger=None,
        profile_synthesis_service=None,
    )
    fake = _FakeStore(synthesis_cfg={"volume_threshold": 40})
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert fake.get_called_keys == []


@pytest.mark.asyncio
async def test_load_runtime_thresholds_db_error_does_not_break_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient DB error on the synthesis read must not break boot."""
    trigger = _trigger()
    service = _service()
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        emotional_detector=None,
        profile_synthesis_trigger=trigger,
        profile_synthesis_service=service,
    )
    monkeypatch.setattr(
        "diana.composition.SqlSystemConfigStore", lambda _sf: _BoomStore()
    )
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    # Boot survived; thresholds keep their defaults.
    assert trigger._volume_threshold == 25  # noqa: SLF001
    assert service._confidence_min == 0.6  # noqa: SLF001
