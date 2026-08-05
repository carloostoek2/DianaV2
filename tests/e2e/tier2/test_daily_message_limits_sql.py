"""E2E: SqlDailyMessageLimitStore on real Postgres (F4-02 atencion).

Exercises the actual repository method (ORM statement generation, session
lifecycle, commit placement, ``scalar_one()``) instead of a hand-copied SQL
string: two increments land on 1 and 2 without drift, a new ``fecha_local``
civil date starts a fresh row at 1, and concurrent increments serialize to
distinct counts (1 and 2) with a third landing on 3.

Runs on the session-level migrated DB (parent ``engine`` fixture applies
``alembic upgrade head``); rows written here are DELETEd at the end so other
tier2 tests are never polluted.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.repositories.daily_message_limits import (
    SqlDailyMessageLimitStore,
)

_CHAT = 988221
_DAY = date(2026, 8, 5)
_DAY2 = date(2026, 8, 6)

_DELETE = text(
    "DELETE FROM daily_message_limits "
    "WHERE chat_id = :chat_id AND fecha_local = :fecha_local"
)


def _store(engine) -> SqlDailyMessageLimitStore:
    """Build the real repo bound to the test engine's session factory."""
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return SqlDailyMessageLimitStore(sf)


async def _cleanup(engine, *days: date) -> None:
    async with engine.begin() as conn:
        for day in days:
            await conn.execute(_DELETE, {"chat_id": _CHAT, "fecha_local": day})


@pytest.mark.db
@pytest.mark.asyncio
async def test_on_conflict_increment_is_atomic(engine) -> None:
    store = _store(engine)
    try:
        first = await store.increment(_CHAT, fecha_local=_DAY)
        assert first == 1
        second = await store.increment(_CHAT, fecha_local=_DAY)
        assert second == 2
        async with engine.begin() as conn:
            stored = (
                await conn.execute(
                    text(
                        "SELECT count FROM daily_message_limits "
                        "WHERE chat_id = :chat_id AND fecha_local = :fecha_local"
                    ),
                    {"chat_id": _CHAT, "fecha_local": _DAY},
                )
            ).scalar_one()
        assert stored == 2
    finally:
        await _cleanup(engine, _DAY)


@pytest.mark.db
@pytest.mark.asyncio
async def test_new_local_day_resets_count(engine) -> None:
    store = _store(engine)
    try:
        first = await store.increment(_CHAT, fecha_local=_DAY)
        assert first == 1
        # Same chat, new civil date → fresh row, counter restarts at 1.
        second = await store.increment(_CHAT, fecha_local=_DAY2)
        assert second == 1
    finally:
        await _cleanup(engine, _DAY, _DAY2)


@pytest.mark.db
@pytest.mark.asyncio
async def test_concurrent_increments_serialize(engine) -> None:
    store = _store(engine)
    try:
        results = await asyncio.gather(
            store.increment(_CHAT, fecha_local=_DAY),
            store.increment(_CHAT, fecha_local=_DAY),
        )
        # ON CONFLICT serializes the pair → counts land on 1 and 2, no drift.
        assert sorted(results) == [1, 2]
        third = await store.increment(_CHAT, fecha_local=_DAY)
        assert third == 3
    finally:
        await _cleanup(engine, _DAY)
