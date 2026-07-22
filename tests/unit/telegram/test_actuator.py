"""AiogramTelegramActuator always passes business_connection_id."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from diana.telegram.actuator import AiogramTelegramActuator


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.read_business_message = AsyncMock()
    b.send_chat_action = AsyncMock()
    b.send_message = AsyncMock(return_value=SimpleNamespace(message_id=77))
    return b


@pytest.mark.asyncio
async def test_send_message_passes_bc(bot: MagicMock) -> None:
    act = AiogramTelegramActuator(bot)
    mid = await act.send_message(42, "hola", business_connection_id="bc-9")
    assert mid == 77
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["business_connection_id"] == "bc-9"
    assert kwargs["chat_id"] == 42
    assert kwargs["text"] == "hola"


@pytest.mark.asyncio
async def test_read_and_typing_pass_bc(bot: MagicMock) -> None:
    act = AiogramTelegramActuator(bot)
    await act.read_business_message(42, 5, business_connection_id="bc-1")
    await act.send_chat_action(42, "typing", business_connection_id="bc-1")
    assert bot.read_business_message.await_args.kwargs["business_connection_id"] == "bc-1"
    assert bot.send_chat_action.await_args.kwargs["business_connection_id"] == "bc-1"


@pytest.mark.asyncio
async def test_missing_bc_fail_closed(bot: MagicMock) -> None:
    act = AiogramTelegramActuator(bot)
    with pytest.raises(ValueError, match="business_connection_id"):
        await act.send_message(42, "x", business_connection_id="")
    bot.send_message.assert_not_awaited()
