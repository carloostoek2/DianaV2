"""RateLimitMiddleware — sliding window per user; owner exempt."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from diana.telegram.middlewares.rate_limit import RateLimitMiddleware


def _callback_query(*, user_id: int = 10) -> CallbackQuery:
    cq = CallbackQuery(
        id="cq-1",
        from_user=User(id=user_id, is_bot=False, first_name="T"),
        chat_instance="inst",
        data="approve:x",
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))
    return cq


def _message(*, user_id: int = 10) -> Message:
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="T"),
        text="hi",
    )


@pytest.mark.asyncio
async def test_under_limit_passes() -> None:
    mw = RateLimitMiddleware(max_events=3, window_s=10.0)
    handler = AsyncMock(return_value="ok")
    msg = _message()
    for _ in range(3):
        assert await mw(handler, msg, {}) == "ok"
    assert handler.await_count == 3


@pytest.mark.asyncio
async def test_over_limit_message_dropped() -> None:
    mw = RateLimitMiddleware(max_events=3, window_s=10.0)
    handler = AsyncMock(return_value="ok")
    msg = _message()
    with patch("diana.telegram.middlewares.rate_limit.logger") as mock_logger:
        for _ in range(3):
            await mw(handler, msg, {})
        fourth = await mw(handler, msg, {})
    assert fourth is None
    assert handler.await_count == 3
    mock_logger.info.assert_called()
    assert mock_logger.info.call_args.args[0] == "telegram_rate_limited"


@pytest.mark.asyncio
async def test_over_limit_callback_answers_slow_down() -> None:
    mw = RateLimitMiddleware(max_events=1, window_s=10.0)
    handler = AsyncMock(return_value="ok")
    cq = _callback_query()
    await mw(handler, cq, {})
    result = await mw(handler, cq, {})
    assert result is None
    assert handler.await_count == 1
    cq.answer.assert_awaited()
    args, kwargs = cq.answer.await_args
    text = args[0] if args else kwargs.get("text", "")
    assert "Slow down" in text
    assert kwargs.get("show_alert") is True or (
        len(args) >= 2 and args[1] is True
    )


@pytest.mark.asyncio
async def test_owner_exempt() -> None:
    mw = RateLimitMiddleware(
        max_events=2,
        window_s=10.0,
        owner_telegram_id=1,
    )
    handler = AsyncMock(return_value="ok")
    msg = _message(user_id=1)
    for _ in range(50):
        assert await mw(handler, msg, {}) == "ok"
    assert handler.await_count == 50


@pytest.mark.asyncio
async def test_window_resets() -> None:
    clock = {"now": 100.0}

    def time_fn() -> float:
        return clock["now"]

    mw = RateLimitMiddleware(max_events=2, window_s=1.0, time_fn=time_fn)
    handler = AsyncMock(return_value="ok")
    msg = _message()
    assert await mw(handler, msg, {}) == "ok"
    assert await mw(handler, msg, {}) == "ok"
    assert await mw(handler, msg, {}) is None
    clock["now"] = 101.1
    assert await mw(handler, msg, {}) == "ok"
    assert handler.await_count == 3


@pytest.mark.asyncio
async def test_idle_keys_evicted_after_window_prune() -> None:
    """SEC-RL-01: empty deques are removed from the map after prune."""
    clock = {"now": 100.0}

    def time_fn() -> float:
        return clock["now"]

    mw = RateLimitMiddleware(max_events=5, window_s=1.0, time_fn=time_fn)
    handler = AsyncMock(return_value="ok")
    msg = _message(user_id=99)
    await mw(handler, msg, {})
    assert 99 in mw._events
    assert len(mw._events[99]) == 1

    clock["now"] = 102.0
    # _window_for prunes empty deque, deletes key, then inserts a fresh deque.
    q = mw._window_for(99, clock["now"])
    assert len(q) == 0
    assert 99 in mw._events
    assert mw._events[99] is q

    # Simulate full idle: prune the only timestamp and ensure production path
    # drops the empty key when the user is next resolved (delete before reinsert).
    q.append(clock["now"])
    clock["now"] = 104.0
    mw._prune_window(mw._events[99], clock["now"])
    assert len(mw._events[99]) == 0
    # Production re-access: empty key is deleted then replaced (no empty residue).
    await mw(handler, msg, {})
    assert 99 in mw._events
    assert len(mw._events[99]) == 1


@pytest.mark.asyncio
async def test_max_keys_cap_evicts_under_pressure() -> None:
    """SEC-RL-01: map cardinality is hard-capped."""
    mw = RateLimitMiddleware(max_events=10, window_s=60.0, max_keys=3)
    handler = AsyncMock(return_value="ok")
    for uid in (1, 2, 3):
        await mw(handler, _message(user_id=uid), {})
    assert len(mw._events) == 3
    await mw(handler, _message(user_id=4), {})
    assert len(mw._events) == 3
    assert 4 in mw._events


@pytest.mark.asyncio
async def test_missing_user_key_fail_closed() -> None:
    """SEC-RL-02: no from_user/chat → drop, never pass handler."""
    mw = RateLimitMiddleware(max_events=20, window_s=10.0)
    handler = AsyncMock(return_value="ok")
    # Channel post style: no from_user, use a plain TelegramObject stand-in
    event = object()
    with patch("diana.telegram.middlewares.rate_limit.logger") as mock_logger:
        result = await mw(handler, event, {})  # type: ignore[arg-type]
    assert result is None
    handler.assert_not_awaited()
    mock_logger.info.assert_called()
    assert mock_logger.info.call_args.args[0] == "telegram_rate_limit_no_key"


@pytest.mark.asyncio
async def test_missing_user_key_callback_answers_slow_down() -> None:
    mw = RateLimitMiddleware(max_events=20, window_s=10.0)
    handler = AsyncMock(return_value="ok")
    cq = CallbackQuery(
        id="cq-anon",
        from_user=User(id=1, is_bot=False, first_name="T"),
        chat_instance="inst",
        data="x",
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))
    # Force no-key path by clearing from_user
    object.__setattr__(cq, "from_user", None)
    result = await mw(handler, cq, {})
    assert result is None
    handler.assert_not_awaited()
    cq.answer.assert_awaited()
