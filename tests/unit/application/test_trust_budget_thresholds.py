"""Boot hydrate of the trust-budget thresholds from system_config."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from diana.application.ports import TurnCategoryLogRecord
from diana.application.trust_budget_service import (
    DEFAULT_TRUST_BUDGET_DECREMENT,
    DEFAULT_TRUST_BUDGET_INCREMENT,
    DEFAULT_TRUST_BUDGET_INITIAL,
    DEFAULT_TRUST_BUDGET_THRESHOLD,
    DEFAULT_TRUST_DISPERSION_HIGH,
    TrustBudgetService,
)
from diana.composition import load_runtime_thresholds


class _FakeStore:
    """Store stub recording every get() call (no-op/I-O assertions)."""

    def __init__(self, *, trust_cfg: dict[str, Any] | None = None) -> None:
        self._trust = trust_cfg
        self.get_called_keys: list[str] = []

    async def get(self, key: str) -> Any | None:
        self.get_called_keys.append(key)
        if key == "trust_budget":
            return self._trust
        return None

    async def get_autonomous_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_supervised_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_eval_thresholds(self) -> dict[str, Any]:
        return {}


class _BoomStore:
    """Store whose get() raises (transient DB error) on the trust key."""

    async def get(self, key: str) -> Any | None:
        raise RuntimeError("transient db failure")

    async def get_autonomous_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_supervised_thresholds(self) -> dict[str, Any]:
        return {}

    async def get_eval_thresholds(self) -> dict[str, Any]:
        return {}


class _FakeVipTrustBudgetStore:
    """Minimal store satisfying VipTrustBudgetStore for the service instance."""

    async def get_by_vip_and_category(self, vip_id, turn_category):
        return None

    async def increment_autonomous(self, vip_id, turn_category, *, delta, initial):
        raise NotImplementedError

    async def decrement_correction(
        self, vip_id, turn_category, *, delta, initial, correction_time
    ):
        raise NotImplementedError

    async def list_by_vip(self, vip_id):
        return []


class _FakeTurnCategoryLogReader:
    async def get_by_turn_id(self, turn_id) -> TurnCategoryLogRecord | None:
        return None


def _service() -> TrustBudgetService:
    return TrustBudgetService(
        store=_FakeVipTrustBudgetStore(),  # type: ignore[arg-type]
        turn_category_log=_FakeTurnCategoryLogReader(),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_load_runtime_thresholds_applies_trust_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    assert service._initial == DEFAULT_TRUST_BUDGET_INITIAL  # noqa: SLF001
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        trust_budget=service,
    )
    fake = _FakeStore(
        trust_cfg={
            "initial": 0.1,
            "increment": 0.2,
            "decrement": 0.3,
            "threshold": 0.6,
            "dispersion_high": 0.5,
            "trend_window_days": 7,
            "thresholds": {"fatico": 0.4},
        }
    )
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert service._initial == 0.1  # noqa: SLF001
    assert service._increment == 0.2  # noqa: SLF001
    assert service._decrement == 0.3  # noqa: SLF001
    assert service._threshold == 0.6  # noqa: SLF001
    assert service._dispersion_high == 0.5  # noqa: SLF001
    assert service._trend_window_days == 7  # noqa: SLF001
    assert service.get_threshold("fatico") == 0.4


@pytest.mark.asyncio
async def test_load_runtime_thresholds_no_key_keeps_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        trust_budget=service,
    )
    fake = _FakeStore(trust_cfg=None)
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert service._initial == DEFAULT_TRUST_BUDGET_INITIAL  # noqa: SLF001
    assert service._increment == DEFAULT_TRUST_BUDGET_INCREMENT  # noqa: SLF001
    assert service._decrement == DEFAULT_TRUST_BUDGET_DECREMENT  # noqa: SLF001
    assert service._threshold == DEFAULT_TRUST_BUDGET_THRESHOLD  # noqa: SLF001
    assert service._dispersion_high == DEFAULT_TRUST_DISPERSION_HIGH  # noqa: SLF001


@pytest.mark.asyncio
async def test_load_runtime_thresholds_service_none_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """trust_budget None → no DB read on the trust key (no-op, no I/O)."""
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        trust_budget=None,
    )
    fake = _FakeStore(trust_cfg={"threshold": 0.5})
    monkeypatch.setattr("diana.composition.SqlSystemConfigStore", lambda _sf: fake)
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    assert fake.get_called_keys == []


@pytest.mark.asyncio
async def test_load_runtime_thresholds_db_error_does_not_break_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient DB error on the trust read must not break boot."""
    service = _service()
    app = SimpleNamespace(
        runtime_thresholds=None,
        session_factory=object(),
        trust_budget=service,
    )
    monkeypatch.setattr(
        "diana.composition.SqlSystemConfigStore", lambda _sf: _BoomStore()
    )
    await load_runtime_thresholds(app)  # type: ignore[arg-type]
    # Boot survived; thresholds keep their pure defaults.
    assert service._threshold == DEFAULT_TRUST_BUDGET_THRESHOLD  # noqa: SLF001
