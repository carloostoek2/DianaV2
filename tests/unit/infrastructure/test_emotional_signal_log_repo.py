"""Offline port/repo surface tests for emotional_signal_log (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import EmotionalSignalRecord
from diana.infrastructure.db.repositories.emotional_signal import (
    SqlEmotionalSignalLogRepo,
    emotional_signal_log_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _signal(**kw) -> EmotionalSignalRecord:
    data = dict(
        signal_detected=True,
        signal_type="angustia",
        intensity=0.85,
        should_trigger_synthesis=True,
        should_escalate_to_owner=True,
        pipeline_would_have_escalated=False,
    )
    data.update(kw)
    return EmotionalSignalRecord(**data)


def test_emotional_signal_log_mapper_pure() -> None:
    row = SimpleNamespace(
        signal_type="vulnerabilidad",
        intensity=0.6,
        should_trigger_synthesis=True,
        should_escalate_to_owner=False,
        pipeline_would_have_escalated=None,
    )
    record = emotional_signal_log_orm_to_record(row)  # type: ignore[arg-type]
    assert record.signal_type == "vulnerabilidad"
    assert record.should_escalate_to_owner is False
    assert record.pipeline_would_have_escalated is None
    assert record.signal_detected is True


def test_emotional_signal_log_repo_surface() -> None:
    sig = inspect.signature(SqlEmotionalSignalLogRepo.__init__)
    assert "session_factory" in sig.parameters
    repo = SqlEmotionalSignalLogRepo(session_factory=object())  # type: ignore[arg-type]
    for name in ("insert", "list_by_vip", "purge_expired"):
        assert inspect.iscoroutinefunction(getattr(repo, name)), name


class _MemoryEmotionalSignalStore:
    """In-memory SqlEmotionalSignalLogRepo (unit, no Postgres)."""

    def __init__(self) -> None:
        self.rows: list[tuple] = []  # (turn_id, vip_id, signal, created_at)

    async def insert(self, *, turn_id, vip_id, signal: EmotionalSignalRecord) -> None:
        self.rows.append((turn_id, vip_id, signal, _now()))

    async def list_by_vip(self, vip_id) -> list[EmotionalSignalRecord]:
        return [s for _t, _v, s, _c in self.rows if _v == vip_id]

    async def purge_expired(self, ttl_days: int) -> int:
        cutoff = _now() - timedelta(days=ttl_days)
        keep = [r for r in self.rows if r[3] >= cutoff]
        deleted = len(self.rows) - len(keep)
        self.rows = keep
        return deleted


@pytest.mark.asyncio
async def test_memory_store_insert_records_turn_id() -> None:
    store = _MemoryEmotionalSignalStore()
    turn_id = uuid4()
    vip_id = uuid4()
    signal = _signal(signal_type="angustia")
    await store.insert(turn_id=turn_id, vip_id=vip_id, signal=signal)
    assert len(store.rows) == 1
    assert store.rows[0][0] == turn_id
    assert store.rows[0][1] == vip_id


@pytest.mark.asyncio
async def test_memory_store_purge_by_ttl() -> None:
    store = _MemoryEmotionalSignalStore()
    await store.insert(turn_id=uuid4(), vip_id=uuid4(), signal=_signal())
    store.rows[0] = (store.rows[0][0], store.rows[0][1], store.rows[0][2], _now() - timedelta(days=200))
    assert await store.purge_expired(ttl_days=90) == 1
    assert len(store.rows) == 0
