"""Link callback router — owner-gated link:<action>:<event_id> decisions."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Router
from aiogram.types import CallbackQuery, Chat, Message, User

from diana.telegram.handlers.link import build_link_callback_router

OWNER = 999001
LINK_CHAT = 123456


def _mock_link() -> MagicMock:
    link = MagicMock()
    link.handle_decision = AsyncMock(return_value="Suscriptor expulsado.")
    return link


def _router(link: MagicMock) -> Router:
    return build_link_callback_router(link=link, owner_telegram_id=OWNER)


def _callback_query(*, user_id: int, data: str) -> CallbackQuery:
    cq = CallbackQuery(
        id="cq-1",
        from_user=User(id=user_id, is_bot=False, first_name="T"),
        chat_instance="inst",
        data=data,
    )
    object.__setattr__(cq, "answer", AsyncMock(return_value=True))
    msg = Message(
        message_id=7,
        date=0,
        chat=Chat(id=LINK_CHAT, type="channel"),
        from_user=User(id=user_id, is_bot=False, first_name="T"),
        text="x",
    )
    object.__setattr__(msg, "edit_reply_markup", AsyncMock())
    object.__setattr__(cq, "message", msg)
    return cq


@pytest.mark.asyncio
async def test_link_action_routes_to_coordinator() -> None:
    link = _mock_link()
    router = _router(link)
    handler = router.callback_query.handlers[0]
    assert handler.callback is not None
    cq = _callback_query(user_id=OWNER, data="link:expel:evt-1")

    await handler.callback(cq)

    link.handle_decision.assert_awaited_once_with("evt-1", "expel")
    cq.answer.assert_awaited_once_with("Suscriptor expulsado.")


@pytest.mark.asyncio
async def test_non_owner_rejected() -> None:
    link = _mock_link()
    router = _router(link)
    handler = router.callback_query.handlers[0]
    cq = _callback_query(user_id=123, data="link:expel:evt-1")

    await handler.callback(cq)

    cq.answer.assert_awaited_once_with("Not authorized", show_alert=True)
    link.handle_decision.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_edited_after_valid_decision() -> None:
    link = _mock_link()
    router = _router(link)
    handler = router.callback_query.handlers[0]
    cq = _callback_query(user_id=OWNER, data="link:keep:evt-1")

    await handler.callback(cq)

    link.handle_decision.assert_awaited_once_with("evt-1", "keep")
    cq.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


@pytest.mark.asyncio
async def test_invalid_callback_data_alert() -> None:
    link = _mock_link()
    router = _router(link)
    handler = router.callback_query.handlers[0]
    cq = _callback_query(user_id=OWNER, data="link:bad")

    await handler.callback(cq)

    cq.answer.assert_awaited_once_with("Invalid callback", show_alert=True)
    link.handle_decision.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_none_skips_keyboard_clear() -> None:
    link = _mock_link()
    router = _router(link)
    handler = router.callback_query.handlers[0]
    cq = _callback_query(user_id=OWNER, data="link:expel:evt-1")
    object.__setattr__(cq, "message", None)

    await handler.callback(cq)

    link.handle_decision.assert_awaited_once_with("evt-1", "expel")
    cq.answer.assert_awaited_once_with("Suscriptor expulsado.")


@pytest.mark.asyncio
async def test_edit_reply_markup_failure_is_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    link = _mock_link()
    router = _router(link)
    handler = router.callback_query.handlers[0]
    cq = _callback_query(user_id=OWNER, data="link:expel:evt-1")
    cq.message.edit_reply_markup.side_effect = Exception("boom")

    with caplog.at_level(logging.DEBUG, logger="diana.telegram"):
        await handler.callback(cq)

    link.handle_decision.assert_awaited_once_with("evt-1", "expel")
    cq.answer.assert_awaited_once_with("Suscriptor expulsado.")
    assert any(r.getMessage() == "link_clear_keyboard_failed" for r in caplog.records)
