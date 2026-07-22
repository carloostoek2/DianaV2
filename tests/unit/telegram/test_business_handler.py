"""Business handler maps DTO and calls orchestrator once."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.ports import VipInboundMessage
from diana.telegram.handlers.business import handle_business_message


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
