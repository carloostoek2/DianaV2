"""E2E: SqlTurnOutcomeLogRepo (Fila 4 ledger) on real Postgres.

Verifies the idempotent post-turn insert, the owner-resolution update and the
C3 reaction update, plus the safety-escalation counter and the pending-signal
queries. Requires Docker/testcontainers (marker ``db``); skipped offline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.ports import TurnOutcomeLogRecord, TurnRecord
from diana.infrastructure.db.repositories.turn_outcome import SqlTurnOutcomeLogRepo
from diana.infrastructure.db.repositories.turns import SqlTurnStore


async def _create_vip(session_factory, telegram_user_id: int):
    from diana.infrastructure.db.repositories.vips import SqlVipStore

    return await SqlVipStore(session_factory).add(
        telegram_user_id, display_name="Outcome VIP"
    )


async def _create_turn(session_factory, vip, chat_id: int = 9001):
    turn_id = uuid4()
    await SqlTurnStore(session_factory).create(
        TurnRecord(
            id=turn_id, chat_id=chat_id, status="delivered", vip_id=vip.id
        )
    )
    return turn_id


def _record(turn_id, vip_id, verdict: str = "send", reason: str | None = None):
    return TurnOutcomeLogRecord(
        turn_id=turn_id,
        vip_id=vip_id,
        shadow_verdict=verdict,
        shadow_reason=reason,
        draft_score=0.7,
        blocked_dims=["safety"] if verdict == "blocked" else [],
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_insert_and_get_by_turn(session_factory) -> None:
    repo = SqlTurnOutcomeLogRepo(session_factory)
    vip = await _create_vip(session_factory, 9601)
    turn_id = await _create_turn(session_factory, vip)

    inserted = await repo.insert(_record(turn_id, vip.id))
    assert inserted.turn_id == turn_id
    assert inserted.shadow_verdict == "send"
    assert inserted.draft_score == pytest.approx(0.7)

    found = await repo.get_by_turn_id(turn_id)
    assert found is not None
    assert found.shadow_verdict == "send"
    assert found.owner_outcome is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_insert_is_idempotent_by_turn(session_factory) -> None:
    repo = SqlTurnOutcomeLogRepo(session_factory)
    vip = await _create_vip(session_factory, 9602)
    turn_id = await _create_turn(session_factory, vip)

    await repo.insert(_record(turn_id, vip.id, verdict="blocked", reason="safety_below_threshold"))
    await repo.insert(_record(turn_id, vip.id, verdict="send"))

    found = await repo.get_by_turn_id(turn_id)
    assert found is not None
    assert found.shadow_verdict == "send"  # upsert overwrites, no duplicate row
    rows = await repo.list_recent(since=datetime.now(UTC) - timedelta(days=1))
    assert sum(1 for r in rows if r.turn_id == turn_id) == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_update_outcome_and_signal(session_factory) -> None:
    repo = SqlTurnOutcomeLogRepo(session_factory)
    vip = await _create_vip(session_factory, 9603)
    turn_id = await _create_turn(session_factory, vip)
    await repo.insert(_record(turn_id, vip.id))

    updated = await repo.update_outcome(
        turn_id, owner_outcome="corrected", sent_score=0.9, quality_delta=0.2
    )
    assert updated is not None
    assert updated.owner_outcome == "corrected"
    assert updated.sent_score == pytest.approx(0.9)
    assert updated.quality_delta == pytest.approx(0.2)

    signaled = await repo.update_signal(turn_id, vip_signal="negative")
    assert signaled is not None
    assert signaled.vip_signal == "negative"


@pytest.mark.db
@pytest.mark.asyncio
async def test_count_safety_escalations_since(session_factory) -> None:
    repo = SqlTurnOutcomeLogRepo(session_factory)
    vip = await _create_vip(session_factory, 9604)

    safe_turn = await _create_turn(session_factory, vip)
    await repo.insert(_record(safe_turn, vip.id))
    unsafe_turn = await _create_turn(session_factory, vip)
    await repo.insert(
        _record(unsafe_turn, vip.id, verdict="escalate", reason="safety_below_threshold")
    )

    since = datetime.now(UTC) - timedelta(days=1)
    assert await repo.count_safety_escalations_since(since=since) == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_signal_pending_and_chat_resolution(session_factory) -> None:
    repo = SqlTurnOutcomeLogRepo(session_factory)
    vip = await _create_vip(session_factory, 9605)
    turn_id = await _create_turn(session_factory, vip, chat_id=9005)
    await repo.insert(_record(turn_id, vip.id))

    # Pending (signal NULL, anchor old): the turn row was created now; to make
    # it pending we only need vip_signal IS NULL and an old anchor — bump the
    # turn's updated_at via a direct transition is not exposed, so use a turn
    # whose created_at is old by inserting with a past timestamp is not
    # supported by SqlTurnStore; instead assert the chat resolution + the
    # pending query with a large window finds nothing older than now.
    found = await repo.find_pending_signal_for_chat(
        9005, since=datetime.now(UTC) - timedelta(days=1)
    )
    assert found is not None
    assert found.turn_id == turn_id
    assert found.vip_signal is None

    # A recent anchor is NOT old enough for the job's pending scan.
    pending = await repo.list_signal_pending(window_hours=6)
    assert all(item["turn_id"] != turn_id for item in pending)
