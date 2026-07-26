"""DedupMiddleware — drop Telegram redeliveries within TTL (process-local)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from diana.telegram.middlewares.dedup import DedupMiddleware


def _callback_query(*, cq_id: str = "cq-1") -> CallbackQuery:
    cq = CallbackQuery(
        id=cq_id,
        from_user=User(id=1, is_bot=False, first_name="T"),
        chat_instance="inst",
        data="approve:x",
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))
    return cq


def _message() -> Message:
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=1, is_bot=False, first_name="T"),
        text="hi",
    )


@pytest.mark.asyncio
async def test_same_update_id_dropped() -> None:
    mw = DedupMiddleware(ttl_s=300.0)
    handler = AsyncMock(return_value="ok")
    data = {"event_update": SimpleNamespace(update_id=42)}
    msg = _message()
    with patch("diana.telegram.middlewares.dedup.logger") as mock_logger:
        first = await mw(handler, msg, data)
        second = await mw(handler, msg, data)
    assert first == "ok"
    assert second is None
    assert handler.await_count == 1
    mock_logger.info.assert_called()
    assert mock_logger.info.call_args.args[0] == "telegram_update_dedup"


@pytest.mark.asyncio
async def test_distinct_update_ids_pass() -> None:
    mw = DedupMiddleware(ttl_s=300.0)
    handler = AsyncMock(return_value="ok")
    msg = _message()
    r1 = await mw(handler, msg, {"event_update": SimpleNamespace(update_id=1)})
    r2 = await mw(handler, msg, {"event_update": SimpleNamespace(update_id=2)})
    assert r1 == "ok"
    assert r2 == "ok"
    assert handler.await_count == 2


@pytest.mark.asyncio
async def test_callback_id_dedup() -> None:
    mw = DedupMiddleware(ttl_s=300.0)
    handler = AsyncMock(return_value="ok")
    cq = _callback_query(cq_id="same-id")
    with patch("diana.telegram.middlewares.dedup.logger") as mock_logger:
        first = await mw(handler, cq, {})
        second = await mw(handler, cq, {})
    assert first == "ok"
    assert second is None
    assert handler.await_count == 1
    assert mock_logger.info.call_args.args[0] == "telegram_update_dedup"


@pytest.mark.asyncio
async def test_ttl_expiry_allows_replay() -> None:
    clock = {"now": 1000.0}

    def time_fn() -> float:
        return clock["now"]

    mw = DedupMiddleware(ttl_s=0.05, time_fn=time_fn)
    handler = AsyncMock(return_value="ok")
    data = {"event_update": SimpleNamespace(update_id=7)}
    msg = _message()
    first = await mw(handler, msg, data)
    assert first == "ok"
    clock["now"] = 1000.0 + 0.06
    second = await mw(handler, msg, data)
    assert second == "ok"
    assert handler.await_count == 2


@pytest.mark.asyncio
async def test_no_key_passes_through() -> None:
    mw = DedupMiddleware(ttl_s=300.0)
    handler = AsyncMock(return_value="ok")
    msg = _message()
    r1 = await mw(handler, msg, {})
    r2 = await mw(handler, msg, {})
    assert r1 == "ok"
    assert r2 == "ok"
    assert handler.await_count == 2
