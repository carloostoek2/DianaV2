"""ErrorHandlerMiddleware — outermost I/O boundary error swallow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from diana.telegram.middlewares.error_handler import ErrorHandlerMiddleware


def _callback_query() -> CallbackQuery:
    cq = CallbackQuery(
        id="cq-1",
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
async def test_error_handler_logs_and_swallows_handler_exception() -> None:
    mw = ErrorHandlerMiddleware()
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    result = await mw(handler, _message(), {})
    assert result is None
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_error_handler_answers_callback_with_show_alert() -> None:
    mw = ErrorHandlerMiddleware()
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    cq = _callback_query()
    result = await mw(handler, cq, {})
    assert result is None
    cq.answer.assert_awaited_once()
    args, kwargs = cq.answer.await_args
    assert kwargs.get("show_alert") is True or (
        len(args) >= 2 and args[1] is True
    )
    assert "Something went wrong" in (args[0] if args else kwargs.get("text", ""))


@pytest.mark.asyncio
async def test_error_handler_answer_failure_swallowed() -> None:
    mw = ErrorHandlerMiddleware()
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    cq = _callback_query()
    object.__setattr__(
        cq, "answer", AsyncMock(side_effect=RuntimeError("answer failed"))
    )
    result = await mw(handler, cq, {})
    assert result is None


@pytest.mark.asyncio
async def test_error_handler_passes_through_success() -> None:
    mw = ErrorHandlerMiddleware()
    handler = AsyncMock(return_value="ok")
    result = await mw(handler, _message(), {})
    assert result == "ok"
    handler.assert_awaited_once()
