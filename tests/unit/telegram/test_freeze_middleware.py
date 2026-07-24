"""FreezeCheckMiddleware — frozen VIP messages silently dropped."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, User

from diana.application.memory import InMemoryVipStore
from diana.application.ports import VipRecord
from diana.telegram.freeze_middleware import FreezeCheckMiddleware


def _biz_msg(user_id: int, text: str = "hello") -> Message:
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="U"),
        text=text,
        business_connection_id="bc-1",
    )


@pytest.mark.asyncio
async def test_frozen_vip_message_dropped() -> None:
    vips = InMemoryVipStore()
    rec = await vips.add(111, display_name="Vip")
    # Freeze the VIP
    frozen_until = datetime.now(UTC) + timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    mw = FreezeCheckMiddleware(vips=vips)
    handler = AsyncMock(return_value="next")
    data: dict = {"vip_record": VipRecord(
        id=rec.id,
        telegram_user_id=111,
        display_name="Vip",
        is_active=True,
        frozen_until=frozen_until,
    )}
    result = await mw(handler, _biz_msg(111), data)
    assert result is None  # Silently dropped
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_unfrozen_vip_message_passes() -> None:
    vips = InMemoryVipStore()
    rec = await vips.add(222, display_name="Vip")

    mw = FreezeCheckMiddleware(vips=vips)
    handler = AsyncMock(return_value="next")
    data: dict = {"vip_record": VipRecord(
        id=rec.id,
        telegram_user_id=222,
        display_name="Vip",
        is_active=True,
        frozen_until=None,
    )}
    result = await mw(handler, _biz_msg(222), data)
    assert result == "next"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_freeze_passes_through() -> None:
    vips = InMemoryVipStore()
    rec = await vips.add(333, display_name="Vip")
    # Freeze that already expired
    frozen_until = datetime.now(UTC) - timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    mw = FreezeCheckMiddleware(vips=vips)
    handler = AsyncMock(return_value="next")
    data: dict = {"vip_record": VipRecord(
        id=rec.id,
        telegram_user_id=333,
        display_name="Vip",
        is_active=True,
        frozen_until=frozen_until,
    )}
    result = await mw(handler, _biz_msg(333), data)
    assert result == "next"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_vip_record_passes_through() -> None:
    vips = InMemoryVipStore()
    mw = FreezeCheckMiddleware(vips=vips)
    handler = AsyncMock(return_value="next")
    data: dict = {}  # No vip_record
    result = await mw(handler, _biz_msg(444), data)
    assert result == "next"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_message_event_passes_through() -> None:
    """Callback (non-Message) events should be allowed through."""
    vips = InMemoryVipStore()
    mw = FreezeCheckMiddleware(vips=vips)
    handler = AsyncMock(return_value="callback_ok")

    # Simulate a non-Message event (e.g., a simple object with no Message interface)
    class FakeEvent:
        pass

    result = await mw(handler, FakeEvent(), {})
    assert result == "callback_ok"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_without_from_user_passes_through() -> None:
    """A Message with no ``from_user`` should pass through (LOW-5/TEST-5)."""
    vips = InMemoryVipStore()
    mw = FreezeCheckMiddleware(vips=vips)
    handler = AsyncMock(return_value="next")
    msg = Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        text="hello",
        business_connection_id="bc-1",
    )
    assert msg.from_user is None
    result = await mw(handler, msg, {})
    assert result == "next"
    handler.assert_awaited_once()
