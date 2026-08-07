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
    for name in ("get_by_vip_and_category", "upsert"):
        assert inspect.iscoroutinefunction(getattr(repo, name)), name


class _MemoryVipTrustBudgetStore:
    """In-memory SqlVipTrustBudgetRepo (unit, no Postgres)."""

    def __init__(self) -> None:
        self.rows: dict[tuple, VipTrustBudgetRecord] = {}

    async def get_by_vip_and_category(self, vip_id, turn_category):
        return self.rows.get((vip_id, turn_category))

    async def upsert(self, record: VipTrustBudgetRecord) -> VipTrustBudgetRecord:
        self.rows[(record.vip_id, record.turn_category)] = record
        return record


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
