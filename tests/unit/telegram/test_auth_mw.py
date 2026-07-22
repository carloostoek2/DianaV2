"""Auth allowlist — non-VIP never reaches next handler."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, User

from diana.application.memory import InMemoryVipStore
from diana.telegram.middlewares.auth import AuthMiddleware


def _biz_msg(user_id: int) -> Message:
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="U"),
        text="hola",
        business_connection_id="bc-1",
    )


@pytest.mark.asyncio
async def test_non_vip_dropped() -> None:
    vips = InMemoryVipStore()
    mw = AuthMiddleware(vips=vips)
    handler = AsyncMock(return_value="orch")
    result = await mw(handler, _biz_msg(111), {"business_connection_id": "bc-1"})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_vip_passes_with_vip_id() -> None:
    vips = InMemoryVipStore()
    rec = await vips.add(222, display_name="Vip")
    mw = AuthMiddleware(vips=vips)
    handler = AsyncMock(return_value="ok")
    data: dict = {"business_connection_id": "bc-1"}
    result = await mw(handler, _biz_msg(222), data)
    assert result == "ok"
    handler.assert_awaited_once()
    assert data["vip_id"] == rec.id


@pytest.mark.asyncio
async def test_deactivated_vip_dropped() -> None:
    vips = InMemoryVipStore()
    await vips.add(333)
    await vips.deactivate(333)
    mw = AuthMiddleware(vips=vips)
    handler = AsyncMock(return_value="ok")
    result = await mw(handler, _biz_msg(333), {"business_connection_id": "bc-1"})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_owner_private_dm_dropped() -> None:
    vips = InMemoryVipStore()
    mw = AuthMiddleware(vips=vips)
    event = Message(
        message_id=2,
        date=0,
        chat=Chat(id=111, type="private"),
        from_user=User(id=111, is_bot=False, first_name="X"),
        text="spam keyword encuentro",
        business_connection_id=None,
    )
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(handler, event, {})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_private_passes() -> None:
    vips = InMemoryVipStore()
    mw = AuthMiddleware(vips=vips)
    event = Message(
        message_id=3,
        date=0,
        chat=Chat(id=999001, type="private"),
        from_user=User(id=999001, is_bot=False, first_name="Owner"),
        text="/start",
        business_connection_id=None,
    )
    handler = AsyncMock(return_value="admin")
    result = await mw(handler, event, {"is_owner": True})
    assert result == "admin"
    handler.assert_awaited_once()
