"""VipStore allowlist semantics (InMemory gold)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from diana.application.memory import InMemoryVipStore


@pytest.mark.asyncio
async def test_add_then_is_allowed_true() -> None:
    store = InMemoryVipStore()
    rec = await store.add(1001, display_name="Alice")
    assert rec.telegram_user_id == 1001
    assert rec.is_active is True
    assert await store.is_allowed(1001) is True
    loaded = await store.get_by_telegram_user_id(1001)
    assert loaded is not None
    assert loaded.id == rec.id


@pytest.mark.asyncio
async def test_deactivate_then_not_allowed() -> None:
    store = InMemoryVipStore()
    await store.add(1002)
    assert await store.deactivate(1002) is True
    assert await store.is_allowed(1002) is False
    rec = await store.get_by_telegram_user_id(1002)
    assert rec is not None and rec.is_active is False


@pytest.mark.asyncio
async def test_paused_until_future_not_allowed() -> None:
    store = InMemoryVipStore()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    future = now + timedelta(hours=2)
    rec = await store.add(1003)
    store.set_paused_until(rec.telegram_user_id, future)
    assert await store.is_allowed(1003, now=now) is False
    assert await store.is_allowed(1003, now=future + timedelta(seconds=1)) is True


@pytest.mark.asyncio
async def test_unknown_user_not_allowed() -> None:
    store = InMemoryVipStore()
    assert await store.is_allowed(99999) is False
    assert await store.get_by_telegram_user_id(99999) is None
