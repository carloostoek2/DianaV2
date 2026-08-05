"""E2E: SqlMetricsDataSource atencion counters against real Postgres (REQ-ATN-14).

Exercises the real-SQL counters that back the daily atencion metrics log:
``count_atencion_turns_since`` (pipeline_traces channel filter) and
``count_atencion_limit_reached_on`` (daily_message_limits cap > 20).

Runs on the session-level migrated DB; rows written here are cleaned up so
other tier2 tests are never polluted. Turn timestamps are placed ~30 days in
the FUTURE relative to ``datetime.now(UTC)`` so traces left by other shared-DB
tests (e.g. test_calibration_data atencion rows) can never fall inside this
test's counting window.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from diana.application.ports import TurnRecord
from diana.infrastructure.db.models import DailyMessageLimit, PipelineTrace
from diana.infrastructure.db.repositories.metrics_data import SqlMetricsDataSource
from diana.infrastructure.db.repositories.turns import SqlTurnStore

_DAY = date(2026, 8, 5)
_OTHER_DAY = date(2026, 8, 6)
_NOW = datetime.now(UTC) + timedelta(days=30)


async def _insert_turn_and_trace(
    session_factory,
    *,
    chat_id: int,
    channel_type: str,
    created_at: datetime = _NOW,
) -> object:
    """Create a real turn + pipeline_trace row for the given channel."""
    store = SqlTurnStore(session_factory)
    turn = await store.create(
        TurnRecord(
            id=uuid4(), chat_id=chat_id, status="received", channel_type=channel_type
        )
    )
    async with session_factory() as sess:
        sess.add(
            PipelineTrace(
                turn_id=turn.id,
                chat_id=chat_id,
                channel_type=channel_type,
                created_at=created_at,
            )
        )
        await sess.commit()
    return turn


async def _cleanup(session_factory, turn_ids: list[object], chat_ids: list[int]) -> None:
    async with session_factory() as sess:
        if turn_ids:
            await sess.execute(
                delete(PipelineTrace).where(PipelineTrace.turn_id.in_(turn_ids))
            )
        if chat_ids:
            await sess.execute(
                delete(DailyMessageLimit).where(DailyMessageLimit.chat_id.in_(chat_ids))
            )
        await sess.commit()


@pytest.mark.db
@pytest.mark.asyncio
async def test_count_atencion_turns_since_counts_only_atencion_channel(
    session_factory,
) -> None:
    """REQ-ATN-14: atencion turn counter ignores VIP traces and the cutoff."""
    traces: list[object] = []
    try:
        t1 = await _insert_turn_and_trace(
            session_factory, chat_id=201, channel_type="atencion"
        )
        traces.append(t1.id)
        await _insert_turn_and_trace(session_factory, chat_id=202, channel_type="vip")
        old = await _insert_turn_and_trace(
            session_factory,
            chat_id=203,
            channel_type="atencion",
            created_at=_NOW - timedelta(days=2),
        )
        traces.append(old.id)

        source = SqlMetricsDataSource(session_factory)
        count = await source.count_atencion_turns_since(_NOW - timedelta(hours=1))

        assert count == 1
    finally:
        await _cleanup(session_factory, turn_ids=traces, chat_ids=[])


@pytest.mark.db
@pytest.mark.asyncio
async def test_count_atencion_limit_reached_on_counts_capped_chats(
    session_factory,
) -> None:
    """REQ-ATN-14: cap counter tallies chats past the 20-message cap (> 20)."""
    try:
        async with session_factory() as sess:
            sess.add_all(
                [
                    DailyMessageLimit(chat_id=301, fecha_local=_DAY, count=25),
                    DailyMessageLimit(chat_id=302, fecha_local=_DAY, count=5),
                    DailyMessageLimit(chat_id=303, fecha_local=_DAY, count=21),
                ]
            )
            await sess.commit()

        source = SqlMetricsDataSource(session_factory)
        assert await source.count_atencion_limit_reached_on(_DAY) == 2
        assert await source.count_atencion_limit_reached_on(_OTHER_DAY) == 0
    finally:
        await _cleanup(session_factory, turn_ids=[], chat_ids=[301, 302, 303])


@pytest.mark.db
@pytest.mark.asyncio
async def test_count_atencion_turns_since_zero_in_future_window(session_factory) -> None:
    """No traces can match a future cutoff → always 0 (shared-DB independent)."""
    source = SqlMetricsDataSource(session_factory)
    count = await source.count_atencion_turns_since(_NOW + timedelta(days=365))
    assert count == 0
