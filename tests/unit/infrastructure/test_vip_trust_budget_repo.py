"""Offline port/repo surface tests for vip_trust_budget (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import VipTrustBudgetRecord
from diana.infrastructure.db.repositories.vip_trust_budget import (
    SqlVipTrustBudgetRepo,
    vip_trust_budget_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _record(**kw) -> VipTrustBudgetRecord:
    data = dict(
        vip_id=uuid4(),
        turn_category="emocional",
        trust_score=0.7,
        correction_count=1,
        autonomous_count=3,
        last_correction_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    data.update(kw)
    return VipTrustBudgetRecord(**data)


def test_vip_trust_budget_mapper_pure() -> None:
    row = SimpleNamespace(
        vip_id=uuid4(),
        turn_category="fatico",
        trust_score=0.9,
        correction_count=0,
        autonomous_count=5,
        last_correction_at=None,
        created_at=_now(),
        updated_at=_now(),
    )
    record = vip_trust_budget_orm_to_record(row)  # type: ignore[arg-type]
    assert record.turn_category == "fatico"
    assert record.trust_score == 0.9
    assert record.autonomous_count == 5
    assert record.last_correction_at is None


def test_vip_trust_budget_repo_surface() -> None:
    sig = inspect.signature(SqlVipTrustBudgetRepo.__init__)
    assert "session_factory" in sig.parameters
    repo = SqlVipTrustBudgetRepo(session_factory=object())  # type: ignore[arg-type]
    for name in (
        "get_by_vip_and_category",
        "upsert",
        "increment_autonomous",
        "decrement_correction",
        "list_by_vip",
    ):
        assert inspect.iscoroutinefunction(getattr(repo, name)), name


class _MemoryVipTrustBudgetStore:
    """In-memory SqlVipTrustBudgetRepo (unit, no Postgres).

    Mirrors the SQL repo semantics: atomic deltas with clamp [0, 1] and the
    counter increments — the Fase 5 service and ficha tests rely on this fake.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple, VipTrustBudgetRecord] = {}

    async def get_by_vip_and_category(self, vip_id, turn_category):
        return self.rows.get((vip_id, turn_category))

    async def upsert(self, record: VipTrustBudgetRecord) -> VipTrustBudgetRecord:
        self.rows[(record.vip_id, record.turn_category)] = record
        return record

    async def increment_autonomous(self, vip_id, turn_category, *, delta, initial):
        key = (vip_id, turn_category)
        current = self.rows.get(key)
        if current is None:
            score = min(1.0, max(0.0, float(initial) + float(delta)))
            record = VipTrustBudgetRecord(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=score,
                autonomous_count=1,
            )
        else:
            score = min(1.0, max(0.0, current.trust_score + float(delta)))
            record = current.model_copy(
                update={
                    "trust_score": score,
                    "autonomous_count": current.autonomous_count + 1,
                }
            )
        self.rows[key] = record
        return record

    async def decrement_correction(
        self, vip_id, turn_category, *, delta, initial, correction_time
    ):
        key = (vip_id, turn_category)
        current = self.rows.get(key)
        if current is None:
            score = min(1.0, max(0.0, float(initial) - float(delta)))
            record = VipTrustBudgetRecord(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=score,
                correction_count=1,
                last_correction_at=correction_time,
            )
        else:
            score = min(1.0, max(0.0, current.trust_score - float(delta)))
            record = current.model_copy(
                update={
                    "trust_score": score,
                    "correction_count": current.correction_count + 1,
                    "last_correction_at": correction_time,
                }
            )
        self.rows[key] = record
        return record

    async def list_by_vip(self, vip_id):
        rows = [r for (vid, _cat), r in self.rows.items() if vid == vip_id]
        return sorted(rows, key=lambda r: r.turn_category)


@pytest.mark.asyncio
async def test_memory_store_upsert_by_pair() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    rec = _record(vip_id=vip, turn_category="informativo", trust_score=0.4)
    await store.upsert(rec)
    assert (await store.get_by_vip_and_category(vip, "informativo")).trust_score == 0.4
    assert await store.get_by_vip_and_category(vip, "emocional") is None

    updated = rec.model_copy(update={"trust_score": 0.6})
    await store.upsert(updated)
    assert (await store.get_by_vip_and_category(vip, "informativo")).trust_score == 0.6
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_memory_store_increment_creates_and_accumulates() -> None:
    """Idempotency: 2 increments → autonomous_count 2, score accumulates."""
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()

    first = await store.increment_autonomous(vip, "fatico", delta=0.05, initial=0.2)
    second = await store.increment_autonomous(vip, "fatico", delta=0.05, initial=0.2)

    assert first.trust_score == pytest.approx(0.25)
    assert second.trust_score == pytest.approx(0.3)
    assert second.autonomous_count == 2
    assert (await store.get_by_vip_and_category(vip, "fatico")).autonomous_count == 2


@pytest.mark.asyncio
async def test_memory_store_delta_clamps_unit_range() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()

    top = await store.increment_autonomous(vip, "fatico", delta=2.0, initial=0.2)
    assert top.trust_score == pytest.approx(1.0)

    bottom = await store.decrement_correction(
        vip, "fatico", delta=3.0, initial=0.2, correction_time=_now()
    )
    assert bottom.trust_score == pytest.approx(0.0)
    assert bottom.correction_count == 1
    assert bottom.last_correction_at is not None


@pytest.mark.asyncio
async def test_memory_store_list_by_vip_ordered_by_category() -> None:
    store = _MemoryVipTrustBudgetStore()
    vip = uuid4()
    other = uuid4()
    for cat in ("informativo", "fatico", "emocional"):
        await store.increment_autonomous(vip, cat, delta=0.05, initial=0.2)
    await store.increment_autonomous(other, "fatico", delta=0.05, initial=0.2)

    rows = await store.list_by_vip(vip)

    assert [r.turn_category for r in rows] == ["emocional", "fatico", "informativo"]
    assert all(r.vip_id == vip for r in rows)


def test_trust_score_validated_to_unit_range() -> None:
    """Spec documents trust_score as [0, 1]; the record enforces it."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _record(trust_score=1.5)
    with pytest.raises(ValidationError):
        _record(trust_score=-0.1)
    # Inclusive bounds are accepted.
    assert _record(trust_score=0.0).trust_score == 0.0
    assert _record(trust_score=1.0).trust_score == 1.0
