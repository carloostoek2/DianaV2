"""Boot hydrate of RuntimeThresholds from system_config (R2 residual)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from diana.application.runtime_thresholds import RuntimeThresholds
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS
from diana.composition import load_runtime_thresholds


class _FakeStore:
    def __init__(
        self,
        *,
        auto: dict[str, Any] | None = None,
        supervised: dict[str, Any] | None = None,
        eval_th: dict[str, Any] | None = None,
    ) -> None:
        self._auto = auto or {}
        self._sup = supervised or {}
        self._eval = eval_th or {}

    async def get_autonomous_thresholds(self) -> dict[str, Any]:
        return dict(self._auto)

    async def get_supervised_thresholds(self) -> dict[str, Any]:
        return dict(self._sup)

    async def get_eval_thresholds(self) -> dict[str, Any]:
        return dict(self._eval)


@pytest.mark.asyncio
async def test_load_runtime_thresholds_applies_autonomous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = RuntimeThresholds(autonomous=dict(DEFAULT_AUTONOMOUS_THRESHOLDS))
    app = SimpleNamespace(runtime_thresholds=holder, session_factory=object())
    fake = _FakeStore(
        auto={"safety_min": 0.95, "doctrine_min": 0.85, "naturalness_min": 0.75}
    )
    monkeypatch.setattr(
        "diana.composition.SqlSystemConfigStore",
        lambda _sf: fake,
    )
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert holder.autonomous["safety_min"] == 0.95
    assert holder.autonomous["doctrine_min"] == 0.85


@pytest.mark.asyncio
async def test_load_runtime_thresholds_noop_without_holder() -> None:
    app = SimpleNamespace(runtime_thresholds=None, session_factory=object())
    await load_runtime_thresholds(app)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_load_runtime_thresholds_safety_from_eval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = RuntimeThresholds()
    app = SimpleNamespace(runtime_thresholds=holder, session_factory=object())
    fake = _FakeStore(eval_th={"safety": 0.42})
    monkeypatch.setattr(
        "diana.composition.SqlSystemConfigStore",
        lambda _sf: fake,
    )
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert holder.safety == 0.42
