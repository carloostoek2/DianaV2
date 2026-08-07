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
        self.history: list[dict] = []

    async def get_by_vip(self, vip_id):
        return self.rows.get(vip_id)

    async def get_or_create(self, vip_id) -> VipProfileRecord:
        row = self.rows.get(vip_id)
        if row is not None:
            return row
        return VipProfileRecord(
            vip_id=vip_id,
            stable_traits={},
            recent_trend={},
            sensitivities=[],
            version=0,
            last_synthesized_at=None,
            synthesis_trigger=None,
        )

    async def save_synthesis_result(
        self, vip_id, *, previous, next, changes_summary
    ) -> VipProfileRecord:
        # Mirror the repo's atomic write: the snapshot of the PRIOR profile is
        # recorded before the upsert; a single logical commit means the profile
        # row reflects the new record only when the snapshot step succeeded.
        if previous is not None:
            self.history.append(
                {
                    "vip_id": vip_id,
                    "version": previous.version,
                    "profile_snapshot": previous.model_dump(
                        mode="json", exclude={"vip_id"}
                    ),
                    "diff_summary": changes_summary,
                }
            )
        self.rows[vip_id] = next
        self.inserted.append(next)
        return next

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


# ---------------------------------------------------------------------------
# Fase 1: get_or_create + save_synthesis_result (atomic snapshot + upsert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_returns_empty_default_without_writing() -> None:
    store = _MemoryVipProfileStore()
    vip = uuid4()
    created = await store.get_or_create(vip)
    assert created.vip_id == vip
    assert created.version == 0
    assert created.stable_traits == {}
    assert created.sensitivities == []
    assert created.last_synthesized_at is None
    # Read-only: nothing was persisted (no row, no history snapshot).
    assert vip not in store.rows
    assert store.history == []


@pytest.mark.asyncio
async def test_get_or_create_returns_existing_when_present() -> None:
    store = _MemoryVipProfileStore()
    rec = _record(version=3, last_synthesized_at=_now())
    await store.insert(rec)
    assert await store.get_or_create(rec.vip_id) == rec


@pytest.mark.asyncio
async def test_save_synthesis_result_previous_none_only_upserts() -> None:
    """previous=None (first synthesis / low confidence) → no snapshot."""
    store = _MemoryVipProfileStore()
    vip = uuid4()
    now = _now()
    nxt = VipProfileRecord(
        vip_id=vip,
        stable_traits={"dedicada": True},
        recent_trend={"cercania": 0.8},
        sensitivities=[{"trait": "apertura", "weight": 0.6}],
        version=0,
        last_synthesized_at=now,
        synthesis_trigger="volume",
    )
    saved = await store.save_synthesis_result(
        vip, previous=None, next=nxt, changes_summary=None
    )
    assert saved == nxt
    assert store.rows[vip] == nxt
    assert store.history == []


@pytest.mark.asyncio
async def test_save_synthesis_result_previous_snapshots_and_bumps() -> None:
    """previous + version+1 → snapshot with previous.version + diff_summary."""
    store = _MemoryVipProfileStore()
    prev = _record(version=1, last_synthesized_at=_now())
    await store.insert(prev)
    now = _now()
    nxt = prev.model_copy(
        update={
            "version": 2,
            "recent_trend": {"cercania": 0.9},
            "last_synthesized_at": now,
            "synthesis_trigger": "emotional_signal",
        }
    )
    await store.save_synthesis_result(
        prev.vip_id, previous=prev, next=nxt, changes_summary="more openness"
    )
    assert store.rows[prev.vip_id].version == 2
    assert len(store.history) == 1
    snap = store.history[0]
    assert snap["vip_id"] == prev.vip_id
    assert snap["version"] == 1  # snapshot carries the PRIOR version
    assert snap["diff_summary"] == "more openness"
    # The snapshot excludes vip_id (model_dump exclude={"vip_id"}).
    assert "vip_id" not in snap["profile_snapshot"]
    assert snap["profile_snapshot"]["version"] == 1


@pytest.mark.asyncio
async def test_save_synthesis_result_low_keeps_traits_keeps_version() -> None:
    """Low-confidence branch: same version, no snapshot, only recent_trend changes."""
    store = _MemoryVipProfileStore()
    prev = _record(
        version=2,
        stable_traits={"dedicada": True},
        sensitivities=[{"trait": "apertura", "weight": 0.6}],
        last_synthesized_at=_now(),
    )
    await store.insert(prev)
    nxt = prev.model_copy(
        update={
            "recent_trend": {"cercania": 0.4},
            "last_synthesized_at": _now(),
            "synthesis_trigger": "volume",
        }
    )
    await store.save_synthesis_result(
        prev.vip_id, previous=None, next=nxt, changes_summary=None
    )
    saved = store.rows[prev.vip_id]
    assert saved.version == 2  # unchanged
    assert saved.stable_traits == {"dedicada": True}  # intact
    assert saved.sensitivities == [{"trait": "apertura", "weight": 0.6}]  # intact
    assert saved.recent_trend == {"cercania": 0.4}  # only recent_trend changed
    assert store.history == []  # no snapshot on the low branch
