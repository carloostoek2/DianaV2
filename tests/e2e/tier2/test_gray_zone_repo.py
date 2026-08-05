"""E2E: GrayZoneQueryRepo atencion lookup against real PostgreSQL.

Covers the F4 atencion path: ``insert`` persists the nullable ``chat_id``
and ``get_open_by_chat_id`` returns the most recent OPEN query for a chat
(A1 — the open row is the atencion chat freeze).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.ports import TurnRecord
from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo
from diana.infrastructure.db.repositories.turns import SqlTurnStore


def _future_freeze() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


async def _new_turn(session_factory, chat_id: int) -> object:
    """Create a real turn row (gray_zone_queries.turn_id has an FK to turns)."""
    store = SqlTurnStore(session_factory)
    return await store.create(
        TurnRecord(id=uuid4(), chat_id=chat_id, status="received")
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_insert_persists_chat_id(session_factory):
    """A1: insert with chat_id round-trips the atencion anchor."""
    repo = GrayZoneQueryRepo(session_factory)
    turn = await _new_turn(session_factory, 4242)
    row = await repo.insert(
        vip_id=None,
        turn_id=turn.id,
        question="q",
        draft="d",
        freeze_until=_future_freeze(),
        chat_id=4242,
    )
    stored = await repo.get_by_id(row.id)
    assert stored is not None
    assert stored.chat_id == 4242
    assert stored.vip_id is None
    assert stored.status == "open"


@pytest.mark.db
@pytest.mark.asyncio
async def test_insert_default_chat_id_none(session_factory):
    """VIP insert keeps chat_id NULL (flag OFF byte-identity)."""
    from diana.infrastructure.db.repositories.vips import SqlVipStore

    vip_store = SqlVipStore(session_factory)
    vip = await vip_store.add(1001, display_name="Vip")
    repo = GrayZoneQueryRepo(session_factory)
    turn = await _new_turn(session_factory, 100)
    row = await repo.insert(
        vip_id=vip.id,
        turn_id=turn.id,
        question="q",
        draft="d",
        freeze_until=_future_freeze(),
    )
    stored = await repo.get_by_id(row.id)
    assert stored is not None
    assert stored.chat_id is None
    assert stored.vip_id == vip.id


@pytest.mark.db
@pytest.mark.asyncio
async def test_insert_persists_business_connection_id(session_factory):
    """F4: insert round-trips business_connection_id (supervised delivery)."""
    repo = GrayZoneQueryRepo(session_factory)
    turn = await _new_turn(session_factory, 4343)
    row = await repo.insert(
        vip_id=None,
        turn_id=turn.id,
        question="q",
        draft="d",
        freeze_until=_future_freeze(),
        chat_id=4343,
        business_connection_id="bc-4343",
    )
    stored = await repo.get_by_id(row.id)
    assert stored is not None
    assert stored.business_connection_id == "bc-4343"
    assert stored.chat_id == 4343


@pytest.mark.db
@pytest.mark.asyncio
async def test_insert_default_business_connection_id_none(session_factory):
    """F4: legacy insert keeps business_connection_id NULL (flag OFF identity)."""
    repo = GrayZoneQueryRepo(session_factory)
    turn = await _new_turn(session_factory, 4444)
    row = await repo.insert(
        vip_id=None,
        turn_id=turn.id,
        question="q",
        draft="d",
        freeze_until=_future_freeze(),
        chat_id=4444,
    )
    stored = await repo.get_by_id(row.id)
    assert stored is not None
    assert stored.business_connection_id is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_open_by_chat_id_returns_most_recent_open(session_factory):
    """A1: get_open_by_chat_id returns the newest open row for the chat."""
    repo = GrayZoneQueryRepo(session_factory)
    chat_id = 777
    older_turn = await _new_turn(session_factory, chat_id)
    newer_turn = await _new_turn(session_factory, chat_id)
    other_turn = await _new_turn(session_factory, 888)
    older = await repo.insert(
        vip_id=None,
        turn_id=older_turn.id,
        question="q1",
        draft="d1",
        freeze_until=_future_freeze(),
        chat_id=chat_id,
    )
    newest = await repo.insert(
        vip_id=None,
        turn_id=newer_turn.id,
        question="q2",
        draft="d2",
        freeze_until=_future_freeze(),
        chat_id=chat_id,
    )
    # A different chat must not leak in.
    await repo.insert(
        vip_id=None,
        turn_id=other_turn.id,
        question="other",
        draft="d3",
        freeze_until=_future_freeze(),
        chat_id=888,
    )

    found = await repo.get_open_by_chat_id(chat_id)
    assert found is not None
    assert found.id == newest.id
    assert older.id != newest.id


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_open_by_chat_id_excludes_resolved(session_factory):
    """A1: resolved rows no longer freeze the atencion chat."""
    repo = GrayZoneQueryRepo(session_factory)
    chat_id = 999
    turn = await _new_turn(session_factory, chat_id)
    row = await repo.insert(
        vip_id=None,
        turn_id=turn.id,
        question="q",
        draft="d",
        freeze_until=_future_freeze(),
        chat_id=chat_id,
    )
    await repo.update_status(row.id, "resolved")

    assert await repo.get_open_by_chat_id(chat_id) is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_open_by_chat_id_none_when_no_open(session_factory):
    """A1: no open query for the chat → None (chat not frozen)."""
    repo = GrayZoneQueryRepo(session_factory)
    assert await repo.get_open_by_chat_id(123456) is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_expire_older_than_skips_non_open_rows(session_factory):
    """R-A: conditional UPDATE only expires rows still open at statement time.

    A query resolved (or already expired) concurrently must not be flipped
    back to 'expired' by the expiry sweep — even when it is older than the
    timeout cutoff.
    """
    from sqlalchemy import text

    repo = GrayZoneQueryRepo(session_factory)
    chat_id = 555001
    resolved_turn = await _new_turn(session_factory, chat_id)
    open_turn = await _new_turn(session_factory, chat_id)
    resolved = await repo.insert(
        vip_id=None,
        turn_id=resolved_turn.id,
        question="resolved q",
        draft="d",
        chat_id=chat_id,
    )
    open_row = await repo.insert(
        vip_id=None,
        turn_id=open_turn.id,
        question="open q",
        draft="d",
        chat_id=chat_id,
    )
    # Backdate both rows beyond the timeout cutoff.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE gray_zone_queries SET created_at = now() - interval '2 hours' "
                "WHERE id IN (:a, :b)"
            ),
            {"a": resolved.id, "b": open_row.id},
        )
        await session.commit()
    await repo.update_status(resolved.id, "resolved", resolved_at=datetime.now(UTC))

    expired = await repo.expire_older_than(timeout_hours=1)

    expired_ids = {r.id for r in expired}
    assert open_row.id in expired_ids  # still open + old → expired
    assert resolved.id not in expired_ids  # resolved rows are never re-expired


@pytest.mark.db
@pytest.mark.asyncio
async def test_reopen_query_clears_resolved_at(session_factory):
    """R-A: reopen_query (status 'open') clears resolved_at so the row reads fresh."""
    repo = GrayZoneQueryRepo(session_factory)
    chat_id = 555002
    turn = await _new_turn(session_factory, chat_id)
    row = await repo.insert(
        vip_id=None,
        turn_id=turn.id,
        question="q",
        draft="d",
        chat_id=chat_id,
    )
    await repo.update_status(row.id, "resolved", resolved_at=datetime.now(UTC))

    # reopen_query on the service delegates here: status 'open' clears resolved_at.
    reopened = await repo.update_status(row.id, "open")
    assert reopened is True

    fresh = await repo.get_by_id(row.id)
    assert fresh is not None
    assert fresh.status == "open"
    assert fresh.resolved_at is None
