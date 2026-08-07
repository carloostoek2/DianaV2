"""Offline port/repo surface tests for turn_category_log (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import TurnCategoryLogRecord
from diana.infrastructure.db.repositories.turn_category import (
    SqlTurnCategoryLogRepo,
    turn_category_log_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _record(**kw) -> TurnCategoryLogRecord:
    data = dict(
        id=uuid4(),
        turn_id=uuid4(),
        category="fatico",
        chat_id=100,
        vip_id=uuid4(),
        created_at=_now(),
    )
    data.update(kw)
    return TurnCategoryLogRecord(**data)


def test_turn_category_log_mapper_pure() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        turn_id=uuid4(),
        category="emocional",
        chat_id=7,
        vip_id=None,
        created_at=_now(),
    )
    record = turn_category_log_orm_to_record(row)  # type: ignore[arg-type]
    assert record.category == "emocional"
    assert record.chat_id == 7
    assert record.vip_id is None


def test_turn_category_log_repo_surface() -> None:
    sig = inspect.signature(SqlTurnCategoryLogRepo.__init__)
    assert "session_factory" in sig.parameters
    repo = SqlTurnCategoryLogRepo(session_factory=object())  # type: ignore[arg-type]
    for name in ("insert", "list_recent", "purge_expired"):
        assert inspect.iscoroutinefunction(getattr(repo, name)), name


class _MemoryTurnCategoryLogStore:
    """In-memory SqlTurnCategoryLogRepo (unit, no Postgres)."""

    def __init__(self) -> None:
        self.rows: list[TurnCategoryLogRecord] = []

    async def insert(self, record: TurnCategoryLogRecord) -> TurnCategoryLogRecord:
        self.rows.append(record)
        return record

    async def list_recent(self, chat_id: int, limit: int = 20) -> list[TurnCategoryLogRecord]:
        matches = [r for r in self.rows if r.chat_id == chat_id]
        matches.sort(key=lambda r: r.created_at or _now(), reverse=True)
        return matches[:limit]

    async def purge_expired(self, ttl_days: int) -> int:
        cutoff = _now() - timedelta(days=ttl_days)
        keep = [r for r in self.rows if (r.created_at or _now()) >= cutoff]
        deleted = len(self.rows) - len(keep)
        self.rows = keep
        return deleted


@pytest.mark.asyncio
async def test_memory_store_purge_by_ttl() -> None:
    store = _MemoryTurnCategoryLogStore()
    now = _now()
    fresh = _record(created_at=now)
    stale = _record(created_at=now - timedelta(days=200))
    await store.insert(fresh)
    await store.insert(stale)

    deleted = await store.purge_expired(ttl_days=90)
    assert deleted == 1
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_memory_store_list_recent_limit() -> None:
    store = _MemoryTurnCategoryLogStore()
    chat = 100
    for _ in range(3):
        await store.insert(_record(chat_id=chat))
    assert len(await store.list_recent(chat, limit=2)) == 2


@pytest.mark.asyncio
async def test_memory_store_purge_zero_old_rows_preserves_everything() -> None:
    """Terminal case: nothing older than the TTL → purge returns 0, keeps all."""
    store = _MemoryTurnCategoryLogStore()
    await store.insert(_record(created_at=_now()))
    await store.insert(_record(created_at=_now() - timedelta(days=10)))
    assert await store.purge_expired(ttl_days=90) == 0
    assert len(store.rows) == 2


@pytest.mark.asyncio
async def test_repo_insert_omits_created_at_when_none() -> None:
    """BUG fix: created_at=None must omit the column so server_default=now() runs."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    captured: dict[str, object] = {}
    session = MagicMock()

    def _capture(row: object) -> None:
        captured["row"] = row

    session.add.side_effect = _capture
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield session

    repo = SqlTurnCategoryLogRepo(session_factory=factory)  # type: ignore[arg-type]
    await repo.insert(_record(created_at=None))
    row = captured["row"]
    # ``created_at`` was NOT set on the ORM object → the column is omitted and
    # the DB server_default (now()) fills it. An explicit NULL would violate
    # the NOT NULL constraint.
    assert "created_at" not in row.__dict__  # type: ignore[attr-defined]
