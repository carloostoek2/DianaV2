"""LinkCoordinatorMiddleware — consume [LINK] traffic in link_chat_id only."""

from __future__ import annotations

import json
import logging

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User
from unittest.mock import AsyncMock, MagicMock

from diana.telegram.middlewares.link import LinkCoordinatorMiddleware

LINK_CHAT = 123456


def _message(*, chat_id: int, text: str) -> Message:
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=chat_id, type="channel"),
        from_user=User(id=100, is_bot=False, first_name="Lucien"),
        text=text,
        business_connection_id="bc-1",
    )


def _link_mock() -> MagicMock:
    link = MagicMock()
    link.handle_kick_event = AsyncMock()
    return link


def _kick_payload(**overrides: object) -> str:
    payload = {
        "event": "vip_kicked",
        "event_id": "evt-1",
        "user_id": 12345,
        "username": "@ana",
        "reason": "quitó el acceso",
        "channel_id": 777,
        "channel_name": "Canal VIP",
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.mark.asyncio
async def test_coordination_traffic_consumed_and_forwarded() -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=LINK_CHAT, text="[LINK]" + _kick_payload())

    result = await mw(handler, msg, {})

    assert result is None
    handler.assert_not_awaited()
    link.handle_kick_event.assert_awaited_once_with(
        event_id="evt-1",
        user_id=12345,
        username="@ana",
        reason="quitó el acceso",
        channel_id=777,
        channel_name="Canal VIP",
    )


@pytest.mark.asyncio
async def test_wrong_chat_passes_through() -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=999, text="[LINK]" + _kick_payload())

    result = await mw(handler, msg, {})

    assert result == "handler-result"
    handler.assert_awaited_once()
    link.handle_kick_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_link_text_passes_through() -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=LINK_CHAT, text="hola")

    result = await mw(handler, msg, {})

    assert result == "handler-result"
    handler.assert_awaited_once()
    link.handle_kick_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_flag_off_passes_through() -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=False)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=LINK_CHAT, text="[LINK]" + _kick_payload())

    result = await mw(handler, msg, {})

    assert result == "handler-result"
    handler.assert_awaited_once()
    link.handle_kick_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_invalid_json_consumed_no_crash(caplog: pytest.LogCaptureFixture) -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=LINK_CHAT, text="[LINK] not-json")

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        result = await mw(handler, msg, {})

    assert result is None
    handler.assert_not_awaited()
    link.handle_kick_event.assert_not_awaited()
    assert any(r.getMessage() == "link_malformed" for r in caplog.records)


@pytest.mark.asyncio
async def test_malformed_unexpected_event_consumed(caplog: pytest.LogCaptureFixture) -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=LINK_CHAT, text="[LINK]" + json.dumps({"event": "other"}))

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        result = await mw(handler, msg, {})

    assert result is None
    handler.assert_not_awaited()
    link.handle_kick_event.assert_not_awaited()
    assert any(r.getMessage() == "link_malformed" for r in caplog.records)


@pytest.mark.asyncio
async def test_malformed_missing_event_id_consumed(caplog: pytest.LogCaptureFixture) -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(
        chat_id=LINK_CHAT,
        text="[LINK]" + json.dumps({"event": "vip_kicked", "user_id": 12345, "reason": "r"}),
    )

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        result = await mw(handler, msg, {})

    assert result is None
    handler.assert_not_awaited()
    link.handle_kick_event.assert_not_awaited()
    assert any(r.getMessage() == "link_malformed" for r in caplog.records)


@pytest.mark.asyncio
async def test_malformed_non_object_payload_consumed(caplog: pytest.LogCaptureFixture) -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=LINK_CHAT, text="[LINK] 123")

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        result = await mw(handler, msg, {})

    assert result is None
    handler.assert_not_awaited()
    link.handle_kick_event.assert_not_awaited()
    assert any(r.getMessage() == "link_malformed" for r in caplog.records)


@pytest.mark.asyncio
async def test_malformed_user_id_overflow_consumed(caplog: pytest.LogCaptureFixture) -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    payload = {
        "event": "vip_kicked",
        "event_id": "evt-1",
        "user_id": float("inf"),
        "reason": "r",
    }
    msg = _message(chat_id=LINK_CHAT, text="[LINK]" + json.dumps(payload))

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        result = await mw(handler, msg, {})

    assert result is None
    handler.assert_not_awaited()
    link.handle_kick_event.assert_not_awaited()
    assert any(r.getMessage() == "link_malformed" for r in caplog.records)


# --- pass-through branches (no coordinator call) ---


@pytest.mark.asyncio
async def test_no_link_passes_through() -> None:
    mw = LinkCoordinatorMiddleware(link=None, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=LINK_CHAT, text="[LINK]" + _kick_payload())

    result = await mw(handler, msg, {})

    assert result == "handler-result"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_link_chat_id_passes_through() -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=None, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    msg = _message(chat_id=LINK_CHAT, text="[LINK]" + _kick_payload())

    result = await mw(handler, msg, {})

    assert result == "handler-result"
    handler.assert_awaited_once()
    link.handle_kick_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_message_event_passes_through() -> None:
    link = _link_mock()
    mw = LinkCoordinatorMiddleware(link=link, link_chat_id=LINK_CHAT, enabled=True)
    handler = AsyncMock(return_value="handler-result")
    cq = CallbackQuery(
        id="cq-1",
        from_user=User(id=100, is_bot=False, first_name="Lucien"),
        chat_instance="inst",
        data="link:expel:evt-1",
    )

    result = await mw(handler, cq, {})

    assert result == "handler-result"
    handler.assert_awaited_once_with(cq, {})
    link.handle_kick_event.assert_not_awaited()
