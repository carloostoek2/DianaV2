"""E2E: SqlVipStore CRUD against real PostgreSQL."""
import pytest
from diana.infrastructure.db.repositories.vips import SqlVipStore


@pytest.mark.db
@pytest.mark.asyncio
async def test_add_vip_creates_and_returns_record(session_factory):
    repo = SqlVipStore(session_factory)
    record = await repo.add(111, display_name="Test VIP")
    assert record.telegram_user_id == 111
    assert record.display_name == "Test VIP"
    assert record.is_active


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_by_telegram_user_id_returns_vip(session_factory):
    repo = SqlVipStore(session_factory)
    await repo.add(222, display_name="FindMe")
    record = await repo.get_by_telegram_user_id(222)
    assert record is not None
    assert record.display_name == "FindMe"


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(session_factory):
    repo = SqlVipStore(session_factory)
    record = await repo.get_by_telegram_user_id(999999)
    assert record is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_deactivate_sets_is_active_false(session_factory):
    repo = SqlVipStore(session_factory)
    await repo.add(333)
    ok = await repo.deactivate(333)
    assert ok
    stored = await repo.get_by_telegram_user_id(333)
    assert not stored.is_active


@pytest.mark.db
@pytest.mark.asyncio
async def test_add_reactivates_deactivated(session_factory):
    repo = SqlVipStore(session_factory)
    await repo.add(444, display_name="V1")
    await repo.deactivate(444)
    r2 = await repo.add(444, display_name="V2")
    assert r2.is_active
    assert r2.display_name == "V2"


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_active_excludes_inactive(session_factory):
    repo = SqlVipStore(session_factory)
    await repo.add(555, display_name="Active")
    await repo.add(666, display_name="Inactive")
    await repo.deactivate(666)
    active = await repo.list_active()
    tg_ids = [r.telegram_user_id for r in active]
    assert 555 in tg_ids
    assert 666 not in tg_ids


@pytest.mark.db
@pytest.mark.asyncio
async def test_rename_vip_updates_name(session_factory):
    repo = SqlVipStore(session_factory)
    await repo.add(777, display_name="Old")
    result = await repo.rename(777, "NewName")
    assert result is not None
    assert result.display_name == "NewName"


@pytest.mark.db
@pytest.mark.asyncio
async def test_freeze_vip_sets_frozen_until(session_factory):
    from datetime import UTC, datetime, timedelta
    repo = SqlVipStore(session_factory)
    record = await repo.add(888)
    until = datetime.now(UTC) + timedelta(hours=2)
    await repo.freeze_vip(record.id, until)
    stored = await repo.get_by_telegram_user_id(888)
    assert stored.frozen_until is not None


@pytest.mark.db
@pytest.mark.asyncio
async def test_pause_vip_sets_paused_until(session_factory):
    from datetime import UTC, datetime, timedelta
    repo = SqlVipStore(session_factory)
    record = await repo.add(999)
    until = datetime.now(UTC) + timedelta(minutes=30)
    await repo.pause_vip(record.id, until)
    stored = await repo.get_by_telegram_user_id(999)
    assert stored.paused_until is not None


@pytest.mark.db
@pytest.mark.asyncio
async def test_is_allowed_active_vip(session_factory):
    repo = SqlVipStore(session_factory)
    await repo.add(1111)
    allowed = await repo.is_allowed(1111)
    assert allowed


@pytest.mark.db
@pytest.mark.asyncio
async def test_is_allowed_nonexistent(session_factory):
    repo = SqlVipStore(session_factory)
    allowed = await repo.is_allowed(999999)
    assert not allowed
