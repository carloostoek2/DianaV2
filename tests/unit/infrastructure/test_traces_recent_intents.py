"""Unit tests for SqlTraceStore.get_recent_intents (mocked session)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from diana.infrastructure.db.repositories.traces import SqlTraceStore


def _factory_with_rows(rows: list[tuple]) -> tuple:
    """Return (session_factory, session) where execute().all() yields rows."""
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def factory():
        yield session

    return factory, session


@pytest.mark.asyncio
async def test_get_recent_intents_order_and_limit() -> None:
    t1, t2, t3 = uuid4(), uuid4(), uuid4()
    rows = [
        (t1, {"intent": "precio"}),
        (t2, {"intent": "chat"}),
        (t3, {"intent": "precio"}),
    ]
    factory, _ = _factory_with_rows(rows)
    store = SqlTraceStore(session_factory=factory)
    out = await store.get_recent_intents(42, limit=2)
    assert out == ["precio", "chat"]


@pytest.mark.asyncio
async def test_get_recent_intents_exclude_turn_id() -> None:
    current = uuid4()
    prior = uuid4()
    # Mock returns rows after DB filter; we still unit-test skip of empty + limit.
    rows = [
        (prior, {"intent": "precio"}),
    ]
    factory, session = _factory_with_rows(rows)
    store = SqlTraceStore(session_factory=factory)
    out = await store.get_recent_intents(7, limit=2, exclude_turn_id=current)
    assert out == ["precio"]
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_get_recent_intents_skips_empty_and_null() -> None:
    rows = [
        (uuid4(), {"intent": ""}),
        (uuid4(), {"intent": "   "}),
        (uuid4(), {"topics": ["x"]}),  # missing intent
        (uuid4(), {"intent": "ok"}),
        (uuid4(), None),
    ]
    factory, _ = _factory_with_rows(rows)
    store = SqlTraceStore(session_factory=factory)
    out = await store.get_recent_intents(1, limit=5)
    assert out == ["ok"]


@pytest.mark.asyncio
async def test_get_recent_intents_limit_zero_empty() -> None:
    factory, session = _factory_with_rows([(uuid4(), {"intent": "x"})])
    store = SqlTraceStore(session_factory=factory)
    assert await store.get_recent_intents(1, limit=0) == []
    session.execute.assert_not_awaited()
