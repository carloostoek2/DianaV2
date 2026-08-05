"""E2E: SqlAtencionCycleStore on real Postgres (F4 atencion lifecycle).

Exercises the actual repository methods on the session-level migrated DB:
``start_if_absent`` is idempotent (never resets ``started_at``), ``is_active``
requires an open window (started within ``since`` AND not closed), and
``close_payment`` ends the cycle once (idempotent per chat).

Rows written here are DELETEd at the end so other tier2 tests are never
polluted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.repositories.atencion_cycles import (
    SqlAtencionCycleStore,
)

_CHAT = 988322
_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

_DELETE = text("DELETE FROM atencion_cycles WHERE chat_id = :chat_id")


def _store(engine) -> SqlAtencionCycleStore:
    """Build the real repo bound to the test engine's session factory."""
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return SqlAtencionCycleStore(sf)


async def _cleanup(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(_DELETE, {"chat_id": _CHAT})


@pytest.mark.db
@pytest.mark.asyncio
async def test_cycle_start_is_active_and_close(engine) -> None:
    store = _store(engine)
    await _cleanup(engine)
    try:
        # absent → not active
        assert (
            await store.is_active(_CHAT, since=_NOW - timedelta(days=30), now=_NOW)
            is False
        )
        # start opens the cycle
        await store.start_if_absent(_CHAT, now=_NOW)
        assert (
            await store.is_active(_CHAT, since=_NOW - timedelta(days=30), now=_NOW)
            is True
        )
        # payment closes it → no longer active
        await store.close_payment(_CHAT, now=_NOW)
        assert (
            await store.is_active(_CHAT, since=_NOW - timedelta(days=30), now=_NOW)
            is False
        )
    finally:
        await _cleanup(engine)


@pytest.mark.db
@pytest.mark.asyncio
async def test_cycle_start_idempotent_keeps_original_start(engine) -> None:
    store = _store(engine)
    await _cleanup(engine)
    try:
        await store.start_if_absent(_CHAT, now=_NOW)
        # re-trigger: start_if_absent must NOT reset started_at to a later time
        later = _NOW + timedelta(days=5)
        await store.start_if_absent(_CHAT, now=later)
        # Window semantics: the CALLER defines the window via `since`
        # (auth gate passes since = now - 30d). At now = original_start + 32d
        # the ORIGINAL window (expires +30d) is expired — and it would NOT be
        # if the re-trigger had extended it (extended expiry would be +35d).
        # is_active False here proves the re-trigger never extended the window.
        later_far = _NOW + timedelta(days=32)
        assert (
            await store.is_active(
                _CHAT,
                since=later_far - timedelta(days=30),
                now=later_far,
            )
            is False
        )
        # ... but still active inside the ORIGINAL window
        assert (
            await store.is_active(_CHAT, since=_NOW - timedelta(days=30), now=later)
            is True
        )
    finally:
        await _cleanup(engine)


@pytest.mark.db
@pytest.mark.asyncio
async def test_cycle_close_payment_idempotent(engine) -> None:
    store = _store(engine)
    await _cleanup(engine)
    try:
        await store.start_if_absent(_CHAT, now=_NOW)
        await store.close_payment(_CHAT, now=_NOW)
        # closing twice must not raise and must keep the cycle closed
        await store.close_payment(_CHAT, now=_NOW + timedelta(minutes=5))
        assert (
            await store.is_active(_CHAT, since=_NOW - timedelta(days=30), now=_NOW)
            is False
        )
    finally:
        await _cleanup(engine)
