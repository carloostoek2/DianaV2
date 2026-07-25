"""Unit tests for SqlSystemConfigStore dual threshold readers (A4)."""

from __future__ import annotations

from typing import Any

import pytest

from diana.cognitive.thresholds import (
    DEFAULT_AUTONOMOUS_THRESHOLDS,
    DEFAULT_SUPERVISED_THRESHOLDS,
)
from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore


class _StubStore(SqlSystemConfigStore):
    """Bypass session factory; control get() return values."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    async def get(self, key: str) -> Any | None:
        return self._values.get(key)


@pytest.mark.asyncio
async def test_get_autonomous_thresholds_returns_stored_dict() -> None:
    stored = {"safety_min": 0.95, "doctrine_min": 0.85, "naturalness_min": 0.75}
    store = _StubStore({"autonomous_thresholds": stored})
    assert await store.get_autonomous_thresholds() == stored


@pytest.mark.asyncio
async def test_get_supervised_thresholds_returns_stored_dict() -> None:
    stored = {"safety_min": 0.55, "doctrine_min": 0.45, "naturalness_min": 0.55}
    store = _StubStore({"supervised_thresholds": stored})
    assert await store.get_supervised_thresholds() == stored


@pytest.mark.asyncio
async def test_get_threshold_helpers_missing_return_empty_not_defaults() -> None:
    """A4: no fallback to pure DEFAULT_* — caller applies defaults."""
    store = _StubStore({})
    auto = await store.get_autonomous_thresholds()
    supervised = await store.get_supervised_thresholds()
    assert auto == {}
    assert supervised == {}
    assert auto != dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
    assert supervised != dict(DEFAULT_SUPERVISED_THRESHOLDS)


@pytest.mark.asyncio
async def test_get_threshold_helpers_non_dict_return_empty() -> None:
    store = _StubStore(
        {
            "autonomous_thresholds": "not-a-dict",
            "supervised_thresholds": ["also", "wrong"],
        }
    )
    assert await store.get_autonomous_thresholds() == {}
    assert await store.get_supervised_thresholds() == {}
