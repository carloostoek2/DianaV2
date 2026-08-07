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


@pytest.mark.asyncio
async def test_get_recent_comprehension_returns_non_empty_dicts() -> None:
    t1, t2, t3 = uuid4(), uuid4(), uuid4()
    rows = [
        (t1, {"emotion": "positiva", "intent": "saludar"}),
        (t2, {}),  # empty dict → skipped
        (t3, None),  # None → skipped
    ]
    factory, _ = _factory_with_rows(rows)
    store = SqlTraceStore(session_factory=factory)
    out = await store.get_recent_comprehension(42, limit=5)
    assert out == [{"emotion": "positiva", "intent": "saludar"}]


@pytest.mark.asyncio
async def test_get_recent_comprehension_respects_exclude_turn_id() -> None:
    current = uuid4()
    prior = uuid4()
    rows = [(prior, {"emotion": "triste"})]
    factory, session = _factory_with_rows(rows)
    store = SqlTraceStore(session_factory=factory)
    out = await store.get_recent_comprehension(7, limit=2, exclude_turn_id=current)
    assert out == [{"emotion": "triste"}]
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_get_recent_comprehension_limit_zero_empty() -> None:
    factory, session = _factory_with_rows([(uuid4(), {"emotion": "neutral"})])
    store = SqlTraceStore(session_factory=factory)
    assert await store.get_recent_comprehension(1, limit=0) == []
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_recent_comprehension_all_empty_returns_empty_list() -> None:
    """Terminal case: no non-empty comprehension rows → [] (not a crash)."""
    factory, _ = _factory_with_rows(
        [
            (uuid4(), {}),  # empty dict
            (uuid4(), None),  # None comprehension
            (uuid4(), "not-a-dict"),  # non-dict
        ]
    )
    store = SqlTraceStore(session_factory=factory)
    assert await store.get_recent_comprehension(42, limit=5) == []


@pytest.mark.asyncio
async def test_get_recent_comprehension_filters_terminal_turn_status() -> None:
    """The baseline EXCLUDES failed/superseded turns (``notin_`` semantics).

    FAILED / superseded / aborted turns never finalized their pipeline and
    would pollute the baseline, so they are the exclusion set — asserted via
    the compiled statement (literal binds). ``notin_`` means every OTHER
    status (delivered / escalated / pending_approval / gray_zone) is INCLUDED
    by absence from the exclusion set, so none of them may appear as a literal
    in the compiled WHERE clause.
    """
    factory, session = _factory_with_rows([(uuid4(), {"emotion": "neutral"})])
    store = SqlTraceStore(session_factory=factory)
    await store.get_recent_comprehension(7, limit=2)
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # The exclusion set is EXACTLY {failed, superseded}: a future fix that
    # re-includes SUPERSEDED (or drops either from the NOT IN) changes the
    # compiled clause and fails this assertion.
    assert "NOT IN ('failed', 'superseded')" in compiled
    # Valid baseline statuses are included by absence (they are NOT excluded).
    for literal in ("'delivered'", "'escalated'", "'pending_approval'", "'gray_zone'"):
        assert literal not in compiled
