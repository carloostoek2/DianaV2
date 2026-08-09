"""Startup missed-message recovery — fetches pending updates via getUpdates."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.types import Update

from diana.application.missed_message_recovery import (
    recover_missed_updates,
    wait_missed_recovery_tasks,
)


def _updates(*dicts: dict) -> list[Update]:
    """Convert raw update dicts to aiogram ``Update`` objects."""
    return [Update.model_validate(d) for d in dicts]


def _make_bot_get_updates(*update_lists: list[Update]) -> AsyncMock:
    """Return an AsyncMock for ``bot.get_updates`` that yields update batches.

    Each positional argument is a batch of ``Update`` objects returned from one
    call.  An empty list signals "no more updates" so the while loop exits.
    """

    async def side_effect(**kwargs):  # noqa: ARG001
        if _make_bot_get_updates.calls < len(update_lists):
            result = update_lists[_make_bot_get_updates.calls]
            _make_bot_get_updates.calls += 1
            return result
        return []

    _make_bot_get_updates.calls = 0
    return AsyncMock(side_effect=side_effect)


@pytest.mark.asyncio
async def test_no_pending_updates() -> None:
    """When there are no pending updates the report is empty."""
    bot = AsyncMock()
    bot.get_updates = AsyncMock(return_value=[])
    dispatcher = AsyncMock()

    report = await recover_missed_updates(bot, dispatcher)

    assert report.total_updates == 0
    assert report.recovered_business_messages == 0
    assert report.recovered_regular_messages == 0
    assert report.total_batches == 0
    bot.get_updates.assert_awaited_once()
    dispatcher.feed_update.assert_not_called()


@pytest.mark.asyncio
async def test_recovers_business_messages() -> None:
    """Business messages are counted and fed through the dispatcher."""
    bot = AsyncMock()
    bot.get_updates = _make_bot_get_updates(
        _updates(
            {
                "update_id": 100,
                "business_message": {
                    "message_id": 1,
                    "date": 1700000000,
                    "chat": {"id": 123, "type": "private"},
                    "text": "hola",
                    "business_connection_id": "bc_1",
                },
            },
            {
                "update_id": 101,
                "business_message": {
                    "message_id": 2,
                    "date": 1700000001,
                    "chat": {"id": 456, "type": "private"},
                    "text": "cómo estás?",
                    "business_connection_id": "bc_1",
                },
            },
            {
                "update_id": 102,
                "message": {
                    "message_id": 3,
                    "date": 1700000002,
                    "chat": {"id": 789, "type": "private"},
                    "text": "regular msg",
                },
            },
        ),
    )
    dispatcher = AsyncMock()
    dispatcher.feed_update = AsyncMock()

    report = await recover_missed_updates(bot, dispatcher)
    await wait_missed_recovery_tasks()

    assert report.total_updates == 3
    assert report.recovered_business_messages == 2
    assert report.recovered_regular_messages == 1
    assert report.total_batches == 1
    assert report.handlers_scheduled == 3
    assert dispatcher.feed_update.await_count == 3


@pytest.mark.asyncio
async def test_multiple_batches() -> None:
    """Multiple getUpdates batches are drained correctly."""
    bot = AsyncMock()

    def make_raw(start_id: int, count: int) -> list[dict]:
        return [
            {
                "update_id": start_id + i,
                "business_message": {
                    "message_id": 10 + i,
                    "date": 1700000000 + i,
                    "chat": {"id": 100 + i, "type": "private"},
                    "text": f"msg {i}",
                    "business_connection_id": "bc_1",
                },
            }
            for i in range(count)
        ]

    bot.get_updates = _make_bot_get_updates(
        _updates(*make_raw(100, 2)),
        _updates(*make_raw(102, 2)),
    )
    dispatcher = AsyncMock()
    dispatcher.feed_update = AsyncMock()

    report = await recover_missed_updates(bot, dispatcher)
    await wait_missed_recovery_tasks()

    assert report.total_updates == 4
    assert report.recovered_business_messages == 4
    assert report.recovered_regular_messages == 0
    assert report.total_batches == 2
    assert dispatcher.feed_update.await_count == 4


@pytest.mark.asyncio
async def test_get_updates_offset_passed_correctly() -> None:
    """Offset advances through the batch after each update."""
    bot = AsyncMock()

    call_log: list[int | None] = []

    async def get_updates_side(**kwargs: object) -> list[Update]:
        call_log.append(kwargs.get("offset"))
        if not call_log:  # first call: offset should be None
            return _updates(
                {
                    "update_id": 100,
                    "business_message": {
                        "message_id": 1,
                        "date": 1700000000,
                        "chat": {"id": 1, "type": "private"},
                        "text": "a",
                        "business_connection_id": "bc",
                    },
                },
            )
        return []

    bot.get_updates = AsyncMock(side_effect=get_updates_side)
    dispatcher = AsyncMock()
    dispatcher.feed_update = AsyncMock()

    await recover_missed_updates(bot, dispatcher)
    await wait_missed_recovery_tasks()

    # First call offset = None (earliest unconfirmed)
    assert call_log[0] is None


@pytest.mark.asyncio
async def test_non_business_non_regular_counted_as_total_only() -> None:
    """An update with neither business_message nor message counts toward total only."""
    bot = AsyncMock()
    bot.get_updates = _make_bot_get_updates(
        _updates(
            {
                "update_id": 200,
                "edited_message": {
                    "message_id": 5,
                    "date": 1700000000,
                    "chat": {"id": 1, "type": "private"},
                    "text": "edited text",
                },
            },
        ),
    )
    dispatcher = AsyncMock()
    dispatcher.feed_update = AsyncMock()

    report = await recover_missed_updates(bot, dispatcher)
    await wait_missed_recovery_tasks()

    assert report.total_updates == 1
    assert report.recovered_business_messages == 0
    assert report.recovered_regular_messages == 0
    assert report.total_batches == 1
    assert dispatcher.feed_update.await_count == 1


@pytest.mark.asyncio
async def test_recover_returns_without_waiting_for_slow_handlers() -> None:
    """VIP pre_delay must not block recover_missed_updates (startup hang fix)."""
    import asyncio
    import time

    bot = AsyncMock()
    bot.get_updates = _make_bot_get_updates(
        _updates(
            {
                "update_id": 300,
                "business_message": {
                    "message_id": 1,
                    "date": 1700000000,
                    "chat": {"id": 1, "type": "private"},
                    "text": "slow",
                    "business_connection_id": "bc",
                },
            },
        ),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_feed(*_a: object, **_k: object) -> None:
        started.set()
        await release.wait()

    dispatcher = AsyncMock()
    dispatcher.feed_update = AsyncMock(side_effect=slow_feed)

    t0 = time.monotonic()
    report = await recover_missed_updates(bot, dispatcher)
    elapsed = time.monotonic() - t0

    assert report.total_updates == 1
    assert report.handlers_scheduled == 1
    assert elapsed < 1.0
    await asyncio.wait_for(started.wait(), timeout=1.0)
    # Unblock background task so the suite does not leak a hung task.
    release.set()
    await wait_missed_recovery_tasks(timeout=2.0)
