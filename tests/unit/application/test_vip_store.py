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


@pytest.mark.asyncio
async def test_get_by_id_returns_record() -> None:
    store = InMemoryVipStore()
    rec = await store.add(2001, display_name="Bob")
    loaded = await store.get_by_id(rec.id)
    assert loaded is not None
    assert loaded.telegram_user_id == 2001
    assert loaded.display_name == "Bob"


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_unknown() -> None:
    store = InMemoryVipStore()
    from uuid import uuid4
    assert await store.get_by_id(uuid4()) is None


@pytest.mark.asyncio
async def test_freeze_vip_sets_frozen_until() -> None:
    store = InMemoryVipStore()
    rec = await store.add(2002)
    frozen_until = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    await store.freeze_vip(rec.id, frozen_until)
    loaded = await store.get_by_id(rec.id)
    assert loaded is not None
    assert loaded.frozen_until == frozen_until


@pytest.mark.asyncio
async def test_freeze_vip_unknown_raises() -> None:
    from uuid import uuid4
    store = InMemoryVipStore()
    with pytest.raises(ValueError, match="not found"):
        await store.freeze_vip(uuid4(), datetime.now(UTC))


@pytest.mark.asyncio
async def test_unfreeze_vip_clears_frozen_until() -> None:
    store = InMemoryVipStore()
    rec = await store.add(2003)
    frozen_until = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    await store.freeze_vip(rec.id, frozen_until)
    await store.unfreeze_vip(rec.id)
    loaded = await store.get_by_id(rec.id)
    assert loaded is not None
    assert loaded.frozen_until is None


@pytest.mark.asyncio
async def test_unfreeze_vip_unknown_raises() -> None:
    from uuid import uuid4
    store = InMemoryVipStore()
    with pytest.raises(ValueError, match="not found"):
        await store.unfreeze_vip(uuid4())


@pytest.mark.asyncio
async def test_add_updates_both_indexes() -> None:
    """After add, both get_by_telegram_user_id and get_by_id find the record."""
    store = InMemoryVipStore()
    rec = await store.add(2004)
    by_tg = await store.get_by_telegram_user_id(2004)
    by_id = await store.get_by_id(rec.id)
    assert by_tg is not None and by_id is not None
    assert by_tg.id == by_id.id


@pytest.mark.asyncio
async def test_deactivate_updates_both_indexes() -> None:
    """After deactivate, get_by_id returns the updated record."""
    store = InMemoryVipStore()
    rec = await store.add(2005)
    await store.deactivate(2005)
    by_id = await store.get_by_id(rec.id)
    assert by_id is not None
    assert by_id.is_active is False
