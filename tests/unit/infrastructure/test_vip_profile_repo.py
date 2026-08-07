"""Offline port/repo surface tests for vip_profile (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import VipProfileRecord
from diana.infrastructure.db.repositories.vip_profile import (
    SqlVipProfileRepo,
    vip_profile_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _record(**kw) -> VipProfileRecord:
    data = dict(
        vip_id=uuid4(),
        stable_traits={"dedicada": True},
        recent_trend={"cercania": 0.8},
        sensitivities=[{"trait": "apertura", "weight": 0.6}],
        version=1,
        last_synthesized_at=None,
        synthesis_trigger=None,
    )
    data.update(kw)
    return VipProfileRecord(**data)


def test_vip_profile_mapper_pure() -> None:
    row = SimpleNamespace(
        vip_id=uuid4(),
        stable_traits={"a": 1},
        recent_trend={"b": 2},
        sensitivities=[{"x": 1}],
        version=3,
        last_synthesized_at=_now(),
        synthesis_trigger="emotional_signal",
    )
    record = vip_profile_orm_to_record(row)  # type: ignore[arg-type]
    assert record.version == 3
    assert record.stable_traits == {"a": 1}
    assert record.sensitivities == [{"x": 1}]
    assert record.synthesis_trigger == "emotional_signal"


def test_vip_profile_record_extra_forbid() -> None:
    with pytest.raises(ValueError):
        _record(unexpected="x")


def test_vip_profile_repo_surface() -> None:
    sig = inspect.signature(SqlVipProfileRepo.__init__)
    assert "session_factory" in sig.parameters
    repo = SqlVipProfileRepo(session_factory=object())  # type: ignore[arg-type]
    for name in ("get_by_vip", "insert"):
        assert inspect.iscoroutinefunction(getattr(repo, name)), name


class _MemoryVipProfileStore:
    """In-memory SqlVipProfileRepo (unit, no Postgres) — upsert by vip_id."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.inserted: list[VipProfileRecord] = []

    async def get_by_vip(self, vip_id):
        return self.rows.get(vip_id)

    async def insert(self, record: VipProfileRecord) -> VipProfileRecord:
        # Mirror ON CONFLICT DO UPDATE keyed on vip_id.
        prev = self.rows.get(record.vip_id)
        merged = record.model_copy(
            update={
                "last_synthesized_at": record.last_synthesized_at,
            }
        )
        self.rows[record.vip_id] = merged
        if prev is None:
            self.inserted.append(merged)
        return merged


@pytest.mark.asyncio
async def test_memory_store_upsert_semantics() -> None:
    store = _MemoryVipProfileStore()
    rec = _record(version=1)
    first = await store.insert(rec)
    assert first.vip_id == rec.vip_id
    assert await store.get_by_vip(rec.vip_id) == rec

    v2 = rec.model_copy(update={"version": 2})
    await store.insert(v2)
    assert (await store.get_by_vip(rec.vip_id)).version == 2
    # single row (upsert), insert recorded once
    assert len(store.rows) == 1
    assert len(store.inserted) == 1


@pytest.mark.asyncio
async def test_memory_store_get_missing_returns_none() -> None:
    store = _MemoryVipProfileStore()
    assert await store.get_by_vip(uuid4()) is None
