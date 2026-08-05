"""E2E: atomic per-(chat_id, local-day) client-message upsert on real Postgres.

Covers F4-02: the exact single-statement ``ON CONFLICT`` the repo uses returns
the running count (1 then 2) without drift, and a new ``fecha_local`` civil
date starts a fresh row at 1 — the daily reset has no TTL/inactivity trigger.

Runs on the session-level migrated DB (parent ``engine`` fixture applies
``alembic upgrade head``); rows written here are DELETEd at the end so other
tier2 tests are never polluted.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

_CHAT = 988221
_DAY = date(2026, 8, 5)

_STMT = text(
    """
    INSERT INTO daily_message_limits (chat_id, fecha_local, count)
    VALUES (:chat_id, :fecha_local, 1)
    ON CONFLICT (chat_id, fecha_local)
    DO UPDATE SET count = daily_message_limits.count + 1
    RETURNING count
    """
)

_DELETE = text(
    "DELETE FROM daily_message_limits "
    "WHERE chat_id = :chat_id AND fecha_local = :fecha_local"
)


@pytest.mark.db
@pytest.mark.asyncio
async def test_on_conflict_increment_is_atomic(engine) -> None:
    async with engine.begin() as conn:
        try:
            first = (
                await conn.execute(_STMT, {"chat_id": _CHAT, "fecha_local": _DAY})
            ).scalar_one()
            assert first == 1
            second = (
                await conn.execute(_STMT, {"chat_id": _CHAT, "fecha_local": _DAY})
            ).scalar_one()
            assert second == 2
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
            await conn.execute(_DELETE, {"chat_id": _CHAT, "fecha_local": _DAY})


@pytest.mark.db
@pytest.mark.asyncio
async def test_new_local_day_resets_count(engine) -> None:
    day2 = date(2026, 8, 6)
    async with engine.begin() as conn:
        try:
            first = (
                await conn.execute(_STMT, {"chat_id": _CHAT, "fecha_local": _DAY})
            ).scalar_one()
            assert first == 1
            # Same chat, new civil date → fresh row, counter restarts at 1.
            second = (
                await conn.execute(_STMT, {"chat_id": _CHAT, "fecha_local": day2})
            ).scalar_one()
            assert second == 1
        finally:
            await conn.execute(_DELETE, {"chat_id": _CHAT, "fecha_local": _DAY})
            await conn.execute(_DELETE, {"chat_id": _CHAT, "fecha_local": day2})
