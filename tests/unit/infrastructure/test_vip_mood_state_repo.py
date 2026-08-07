"""Offline port/repo surface tests for vip_mood_state (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import VipMoodStateRecord
from diana.infrastructure.db.repositories.vip_mood_state import (
    SqlVipMoodStateRepo,
    vip_mood_state_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _record(**kw) -> VipMoodStateRecord:
    data = dict(
        vip_id=uuid4(),
        axis_playful_serious=0.2,
        axis_warm_distant=-0.4,
        axis_energy=0.7,
        updated_at=_now(),
    )
    data.update(kw)
    return VipMoodStateRecord(**data)


def test_vip_mood_state_mapper_pure() -> None:
    row = SimpleNamespace(
        vip_id=uuid4(),
        axis_playful_serious=0.5,
        axis_warm_distant=-0.5,
        axis_energy=0.0,
        updated_at=_now(),
    )
    record = vip_mood_state_orm_to_record(row)  # type: ignore[arg-type]
    assert record.axis_playful_serious == 0.5
    assert record.axis_warm_distant == -0.5
    assert record.axis_energy == 0.0


def test_vip_mood_state_repo_surface() -> None:
    sig = inspect.signature(SqlVipMoodStateRepo.__init__)
    assert "session_factory" in sig.parameters
    repo = SqlVipMoodStateRepo(session_factory=object())  # type: ignore[arg-type]
    for name in ("get_by_vip", "upsert"):
        assert inspect.iscoroutinefunction(getattr(repo, name)), name


class _MemoryVipMoodStateStore:
    """In-memory SqlVipMoodStateRepo (unit, no Postgres) — upsert by vip_id."""

    def __init__(self) -> None:
        self.rows: dict = {}

    async def get_by_vip(self, vip_id):
        return self.rows.get(vip_id)

    async def upsert(self, record: VipMoodStateRecord) -> VipMoodStateRecord:
        self.rows[record.vip_id] = record
        return record


@pytest.mark.asyncio
async def test_memory_store_upsert_semantics() -> None:
    store = _MemoryVipMoodStateStore()
    rec = _record(axis_energy=0.3)
    await store.upsert(rec)
    assert (await store.get_by_vip(rec.vip_id)).axis_energy == 0.3

    updated = rec.model_copy(update={"axis_energy": 0.9})
    await store.upsert(updated)
    assert (await store.get_by_vip(rec.vip_id)).axis_energy == 0.9
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_memory_store_get_missing_returns_none() -> None:
    store = _MemoryVipMoodStateStore()
    assert await store.get_by_vip(uuid4()) is None
