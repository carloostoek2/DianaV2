"""Offline port/repo surface tests for the daily message limit (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime

import pytest

from diana.application.mexico_tz import cdmx_local_date
from diana.application.ports import DailyMessageLimitStore
from diana.infrastructure.db.repositories.daily_message_limits import (
    SqlDailyMessageLimitStore,
)


class _MemoryDailyMessageLimitStore:
    """In-memory DailyMessageLimitStore (unit, no Postgres).

    Mirrors the date-keyed semantics of the SQL upsert: a distinct
    ``fecha_local`` is a fresh row whose count starts at 1.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[int, date], int] = {}
        self.calls: list[tuple[int, date]] = []

    async def increment(self, chat_id: int, *, fecha_local: date) -> int:
        self.calls.append((chat_id, fecha_local))
        key = (chat_id, fecha_local)
        self.rows[key] = self.rows.get(key, 0) + 1
        return self.rows[key]


def test_repo_surface_and_protocol_match() -> None:
    sig = inspect.signature(SqlDailyMessageLimitStore.__init__)
    assert "session_factory" in sig.parameters
    repo = SqlDailyMessageLimitStore(session_factory=object())  # type: ignore[arg-type]
    assert inspect.iscoroutinefunction(repo.increment)
    # runtime_checkable duck-typing: repo instance satisfies the protocol.
    assert isinstance(repo, DailyMessageLimitStore)


def test_protocol_method_names_match_store() -> None:
    protocol_names = set(getattr(DailyMessageLimitStore, "__protocol_attrs__", set()))
    repo_names = {"increment"}
    assert protocol_names == repo_names
    fake = _MemoryDailyMessageLimitStore()
    assert isinstance(fake, DailyMessageLimitStore)


@pytest.mark.asyncio
async def test_increment_monotonic_same_day() -> None:
    store = _MemoryDailyMessageLimitStore()
    day = date(2026, 8, 5)
    assert await store.increment(42, fecha_local=day) == 1
    assert await store.increment(42, fecha_local=day) == 2
    assert await store.increment(42, fecha_local=day) == 3
    assert store.calls == [(42, day), (42, day), (42, day)]


@pytest.mark.asyncio
async def test_increment_new_day_resets() -> None:
    store = _MemoryDailyMessageLimitStore()
    assert await store.increment(42, fecha_local=date(2026, 8, 5)) == 1
    assert await store.increment(42, fecha_local=date(2026, 8, 5)) == 2
    # Same chat, new local day → fresh row, count starts at 1.
    assert await store.increment(42, fecha_local=date(2026, 8, 6)) == 1
    # Different chat, same day → independent row.
    assert await store.increment(43, fecha_local=date(2026, 8, 5)) == 1


def test_cdmx_local_date_converts_utc() -> None:
    # 2026-08-05 23:30 UTC → CDMX (UTC-6) → 17:30 the same day.
    value = datetime(2026, 8, 5, 23, 30, tzinfo=UTC)
    assert cdmx_local_date(value) == date(2026, 8, 5)
    # Naive datetimes are treated as UTC (mirror of cognitive _to_cdmx).
    naive = datetime(2026, 8, 5, 23, 30)
    assert cdmx_local_date(naive) == date(2026, 8, 5)


def test_cdmx_local_date_rolls_day_at_midnight() -> None:
    # 2026-08-06 05:30 UTC → CDMX 2026-08-05 23:30 → previous civil day.
    value = datetime(2026, 8, 6, 5, 30, tzinfo=UTC)
    assert cdmx_local_date(value) == date(2026, 8, 5)


def test_repo_increment_is_single_on_conflict_statement() -> None:
    """Source pin: increment must stay one ON CONFLICT ... RETURNING statement."""
    source = inspect.getsource(SqlDailyMessageLimitStore.increment)
    assert "on_conflict_do_update(" in source
    assert "index_elements=[\"chat_id\", \"fecha_local\"]" in source
    assert "returning(DailyMessageLimit.count)" in source
    assert "scalar_one()" in source
    # No separate read-before-write SELECT drift allowed (REQ-ATN-04).
    assert "select(" not in source
