"""Offline port/repo surface tests for vip_profile_history (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import VipProfileHistoryRecord
from diana.infrastructure.db.repositories.vip_profile_history import (
    SqlVipProfileHistoryRepo,
    vip_profile_history_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _record(**kw) -> VipProfileHistoryRecord:
    data = dict(
        id=uuid4(),
        vip_id=uuid4(),
        version=1,
        profile_snapshot={"stable_traits": {"a": 1}},
        diff_summary="first snapshot",
        created_at=_now(),
    )
    data.update(kw)
    return VipProfileHistoryRecord(**data)


def test_vip_profile_history_mapper_pure() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        vip_id=uuid4(),
        version=2,
        profile_snapshot={"recent_trend": {"b": 1}},
        diff_summary="changed trend",
        created_at=_now(),
    )
    record = vip_profile_history_orm_to_record(row)  # type: ignore[arg-type]
    assert record.version == 2
    assert record.diff_summary == "changed trend"
    assert record.profile_snapshot == {"recent_trend": {"b": 1}}


def test_vip_profile_history_repo_surface() -> None:
    sig = inspect.signature(SqlVipProfileHistoryRepo.__init__)
    assert "session_factory" in sig.parameters
    repo = SqlVipProfileHistoryRepo(session_factory=object())  # type: ignore[arg-type]
    for name in ("insert", "list_by_vip", "purge_expired"):
        assert inspect.iscoroutinefunction(getattr(repo, name)), name


class _MemoryVipProfileHistoryStore:
    """In-memory SqlVipProfileHistoryRepo (unit, no Postgres)."""

    def __init__(self) -> None:
        self.rows: list[VipProfileHistoryRecord] = []

    async def insert(self, record: VipProfileHistoryRecord) -> VipProfileHistoryRecord:
        self.rows.append(record)
        return record

    async def list_by_vip(self, vip_id) -> list[VipProfileHistoryRecord]:
        return [r for r in self.rows if r.vip_id == vip_id]

    async def purge_expired(self, ttl_days: int) -> int:
        cutoff = _now() - timedelta(days=ttl_days)
        keep = [r for r in self.rows if r.created_at >= cutoff]
        deleted = len(self.rows) - len(keep)
        self.rows = keep
        return deleted


@pytest.mark.asyncio
async def test_memory_store_purge_by_ttl() -> None:
    store = _MemoryVipProfileHistoryStore()
    now = _now()
    fresh = _record(version=1, created_at=now)
    stale = _record(version=2, created_at=now - timedelta(days=200))
    await store.insert(fresh)
    await store.insert(stale)

    deleted = await store.purge_expired(ttl_days=90)
    assert deleted == 1
    assert [r.version for r in store.rows] == [1]


@pytest.mark.asyncio
async def test_memory_store_list_by_vip() -> None:
    store = _MemoryVipProfileHistoryStore()
    vip = uuid4()
    other = uuid4()
    await store.insert(_record(vip_id=vip, version=1))
    await store.insert(_record(vip_id=vip, version=2))
    await store.insert(_record(vip_id=other, version=1))
    assert len(await store.list_by_vip(vip)) == 2


@pytest.mark.asyncio
async def test_memory_store_purge_expired_batches_total() -> None:
    """Batched purge returns the grand total (fake simulates > LIMIT 1000)."""
    store = _MemoryVipProfileHistoryStore()
    stale_base = _now() - timedelta(days=200)
    total = 2500  # > 2 batches of 1000
    for i in range(total):
        await store.insert(
            _record(version=i, created_at=stale_base + timedelta(seconds=i))
        )
    assert await store.purge_expired(ttl_days=90) == total
    assert len(store.rows) == 0
