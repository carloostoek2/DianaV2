"""Business handler maps DTO and calls orchestrator once."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, User

from diana.application.ports import VipInboundMessage
from diana.telegram.handlers.business import (
    build_business_router,
    handle_business_message,
)


def _biz_message() -> Message:
    return Message(
        message_id=7,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=111, is_bot=False, first_name="Vip"),
        text="hola vip",
        business_connection_id="bc-1",
    )


@pytest.mark.asyncio
async def test_maps_dto_and_calls_orchestrator_once() -> None:
    orch = AsyncMock()
    tid = uuid4()
    orch.handle_vip_message = AsyncMock(return_value=tid)
    vip_id = uuid4()
    result = await handle_business_message(
        orchestrator=orch,
        chat_id=42,
        text="hola vip",
        telegram_message_id=7,
        business_connection_id="bc-1",
        vip_id=vip_id,
    )
    assert result == tid
    orch.handle_vip_message.assert_awaited_once()
    arg = orch.handle_vip_message.await_args.args[0]
    assert isinstance(arg, VipInboundMessage)
    assert arg.chat_id == 42
    assert arg.text == "hola vip"
    assert arg.telegram_message_id == 7
    assert arg.business_connection_id == "bc-1"
    assert arg.vip_id == vip_id


@pytest.mark.asyncio
async def test_pure_helper_propagates_orchestrator_exception() -> None:
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(side_effect=RuntimeError("orch down"))
    with pytest.raises(RuntimeError, match="orch down"):
        await handle_business_message(
            orchestrator=orch,
            chat_id=42,
            text="hola",
            telegram_message_id=1,
            business_connection_id="bc-1",
            vip_id=None,
        )


@pytest.mark.asyncio
async def test_router_maps_channel_type_into_inbound() -> None:
    """F4: the atencion channel travels from aiogram data into VipInboundMessage."""
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(orchestrator=orch)
    on_business = router.business_message.handlers[0].callback
    # aiogram injects data keys (channel_type set by AuthMiddleware) as kwargs.
    await on_business(_biz_message(), channel_type="atencion")
    orch.handle_vip_message.assert_awaited_once()
    arg = orch.handle_vip_message.await_args.args[0]
    assert isinstance(arg, VipInboundMessage)
    assert arg.channel_type == "atencion"
    assert arg.vip_id is None


@pytest.mark.asyncio
async def test_router_default_channel_type_is_vip() -> None:
    """F4: no channel_type in data → VIP default, unchanged behavior."""
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(orchestrator=orch)
    on_business = router.business_message.handlers[0].callback
    await on_business(_biz_message())
    arg = orch.handle_vip_message.await_args.args[0]
    assert arg.channel_type == "vip"


@pytest.mark.asyncio
async def test_router_forwards_counted_marker() -> None:
    """F4-02: atencion_limit_counted travels from aiogram data to counts_toward_limit."""
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(orchestrator=orch)
    on_business = router.business_message.handlers[0].callback
    await on_business(
        _biz_message(), channel_type="atencion", atencion_limit_counted=True
    )
    orch.handle_vip_message.assert_awaited_once()
    arg = orch.handle_vip_message.await_args.args[0]
    assert isinstance(arg, VipInboundMessage)
    assert arg.channel_type == "atencion"
    assert arg.counts_toward_limit is True


@pytest.mark.asyncio
async def test_router_default_counted_false() -> None:
    """F4-02: no marker in data → counts_toward_limit defaults False."""
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(orchestrator=orch)
    on_business = router.business_message.handlers[0].callback
    await on_business(_biz_message(), channel_type="atencion")
    arg = orch.handle_vip_message.await_args.args[0]
    assert isinstance(arg, VipInboundMessage)
    assert arg.counts_toward_limit is False


@pytest.mark.asyncio
async def test_edited_router_forwards_counted_marker() -> None:
    """F4-02: the edited-business path forwards the marker (hook still drops edits)."""
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(orchestrator=orch)
    on_edited = router.edited_business_message.handlers[0].callback
    await on_edited(
        _biz_message(), channel_type="atencion", atencion_limit_counted=True
    )
    orch.handle_vip_message.assert_awaited_once()
    arg = orch.handle_vip_message.await_args.args[0]
    assert arg.is_edit is True
    assert arg.counts_toward_limit is True


@pytest.mark.asyncio
async def test_edited_message_keeps_channel_and_is_edit() -> None:
    """N6: the edited-business path forwards channel_type and flags is_edit."""
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(orchestrator=orch)
    on_edited = router.edited_business_message.handlers[0].callback
    await on_edited(_biz_message(), channel_type="atencion")
    orch.handle_vip_message.assert_awaited_once()
    arg = orch.handle_vip_message.await_args.args[0]
    assert isinstance(arg, VipInboundMessage)
    assert arg.channel_type == "atencion"
    assert arg.is_edit is True
    assert arg.vip_id is None


@pytest.mark.asyncio
async def test_router_swallows_orchestrator_exception() -> None:
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(side_effect=RuntimeError("orch down"))
    router = build_business_router(orchestrator=orch)
    on_business = router.business_message.handlers[0].callback
    with patch("diana.telegram.handlers.business.logger") as mock_logger:
        # Must not raise — router edge swallows.
        await on_business(_biz_message())
    orch.handle_vip_message.assert_awaited_once()
    mock_logger.exception.assert_called()
    assert mock_logger.exception.call_args.args[0] == "business_handler_error"
    extra = mock_logger.exception.call_args.kwargs.get("extra") or {}
    assert extra.get("chat_id") == 42
    assert extra.get("telegram_message_id") == 7
    assert extra.get("business_connection_id") == "bc-1"
