"""Unit tests for SqlSystemConfigStore writers + calibration getter."""

from __future__ import annotations

from typing import Any

import pytest

from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore


class _MemoryStore(SqlSystemConfigStore):
    """In-memory get/set bypassing session factory (unit, no Postgres)."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values: dict[str, Any] = dict(values or {})
        self.set_calls: list[tuple[str, Any]] = []

    async def get(self, key: str) -> Any | None:
        return self._values.get(key)

    async def set(self, key: str, value: Any) -> None:
        self.set_calls.append((key, value))
        self._values[key] = value


@pytest.mark.asyncio
async def test_set_upserts_key() -> None:
    store = _MemoryStore({"a": 1})
    await store.set("a", 2)
    await store.set("b", {"x": True})
    assert await store.get("a") == 2
    assert await store.get("b") == {"x": True}
    assert ("a", 2) in store.set_calls
    assert ("b", {"x": True}) in store.set_calls


@pytest.mark.asyncio
async def test_get_calibration_config_returns_dict() -> None:
    blob = {
        "window_days": 30,
        "min_samples": 50,
        "autonomous_margin_min": 0.05,
    }
    store = _MemoryStore({"calibration": blob})
    assert await store.get_calibration_config() == blob


@pytest.mark.asyncio
async def test_get_calibration_config_missing_or_bad_returns_empty() -> None:
    store = _MemoryStore({})
    assert await store.get_calibration_config() == {}
    store2 = _MemoryStore({"calibration": "nope"})
    assert await store2.get_calibration_config() == {}


@pytest.mark.asyncio
async def test_set_autonomous_thresholds_writes_key() -> None:
    store = _MemoryStore()
    value = {"safety_min": 0.9, "doctrine_min": 0.8, "naturalness_min": 0.7}
    await store.set_autonomous_thresholds(value)
    assert store.set_calls == [("autonomous_thresholds", value)]
    assert await store.get_autonomous_thresholds() == value


@pytest.mark.asyncio
async def test_set_supervised_thresholds_writes_key() -> None:
    store = _MemoryStore()
    value = {"safety_min": 0.5, "doctrine_min": 0.4, "naturalness_min": 0.5}
    await store.set_supervised_thresholds(value)
    assert store.set_calls == [("supervised_thresholds", value)]
    assert await store.get_supervised_thresholds() == value


@pytest.mark.asyncio
async def test_get_training_mode_unset_returns_false() -> None:
    store = _MemoryStore({})
    assert await store.get_training_mode_enabled() is False


@pytest.mark.asyncio
async def test_set_training_mode_roundtrip() -> None:
    store = _MemoryStore({})
    # Set True → get True
    await store.set_training_mode_enabled(True)
    assert await store.get_training_mode_enabled() is True
    assert await store.is_enabled() is True
    # Set False → get False
    await store.set_training_mode_enabled(False)
    assert await store.get_training_mode_enabled() is False
    assert await store.is_enabled() is False
    # Protocol-compatible set_enabled also works
    await store.set_enabled(True)
    assert await store.is_enabled() is True
    assert await store.get_training_mode_enabled() is True


@pytest.mark.asyncio
async def test_set_thresholds_copy_not_shared_mutation() -> None:
    store = _MemoryStore()
    value = {"safety_min": 0.5, "doctrine_min": 0.4, "naturalness_min": 0.5}
    await store.set_supervised_thresholds(value)
    value["safety_min"] = 0.99
    stored = await store.get_supervised_thresholds()
    assert stored["safety_min"] == 0.5
