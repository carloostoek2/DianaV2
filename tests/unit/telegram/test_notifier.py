"""Owner notifier draft markup includes turn_id action codes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from diana.application.ports import (
    DraftNotification,
    EscalationNotification,
    LinkNotification,
)
from diana.telegram.keyboards import encode_callback, parse_callback
from diana.telegram.notifier import AiogramOwnerNotifier


def test_callback_encode_parse_roundtrip() -> None:
    tid = uuid4()
    for action in ("approve", "correct", "escalate"):
        data = encode_callback(action, tid)
        assert len(data.encode()) <= 64
        parsed = parse_callback(data)
        assert parsed == (action, tid)


@pytest.mark.asyncio
async def test_notify_draft_includes_markup_with_turn_id() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=9))
    notifier = AiogramOwnerNotifier(bot, owner_telegram_id=999)
    turn_id = uuid4()
    mid = await notifier.notify_draft(
        DraftNotification(
            turn_id=turn_id,
            chat_id=42,
            vip_text="hi",
            draft_text="draft",
            reason="ok",
            business_connection_id="bc",
        )
    )
    assert mid == 9
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 999
    markup = kwargs["reply_markup"]
    flat = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert any(f"a:{turn_id}" == d for d in flat)
    assert any(f"c:{turn_id}" == d for d in flat)
    assert any(f"e:{turn_id}" == d for d in flat)


@pytest.mark.asyncio
async def test_notify_escalation_sends_dm() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=1))
    notifier = AiogramOwnerNotifier(bot, owner_telegram_id=999)
    await notifier.notify_escalation(
        EscalationNotification(
            turn_id=uuid4(),
            chat_id=42,
            reason="forbidden",
            tipo="palabra_prohibida",
        )
    )
    bot.send_message.assert_awaited_once()

@pytest.mark.asyncio
async def test_notify_escalation_includes_spanish_label() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=1))
    notifier = AiogramOwnerNotifier(bot, owner_telegram_id=999)
    turn_id = uuid4()
    await notifier.notify_escalation(
        EscalationNotification(
            turn_id=turn_id,
            chat_id=42,
            reason="frustracion_directa",
            tipo="frustracion_directa",
            vip_text="estoy molesta",
        )
    )
    kwargs = bot.send_message.await_args.kwargs
    body = kwargs["text"]
    assert "Escalación:" in body
    assert "Frustración directa (VIP molesta)" in body
    assert "[frustracion_directa]" in body
    assert "chat=42" in body
    assert "VIP: estoy molesta" in body
    assert str(turn_id) in body


@pytest.mark.asyncio
async def test_notify_link_includes_approved_copy_and_buttons() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=7))
    notifier = AiogramOwnerNotifier(bot, owner_telegram_id=999)
    mid = await notifier.notify_link(
        LinkNotification(display_name="Ana", username="ana_vip", event_id="evt-1")
    )
    assert mid == 7
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 999
    body = kwargs["text"]
    assert body == (
        "⚠️ ATENCIÓN ⚠️\n"
        "El suscriptor Ana @ana_vip ha sido expulsado del Canal VIP. "
        "¿Quieres inhabilitarlo aquí?"
    )
    markup = kwargs["reply_markup"]
    flat = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert flat == ["link:expel:evt-1", "link:disable:evt-1", "link:keep:evt-1"]


@pytest.mark.asyncio
async def test_notify_link_normalizes_at_prefixed_username() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=7))
    notifier = AiogramOwnerNotifier(bot, owner_telegram_id=999)
    await notifier.notify_link(
        LinkNotification(display_name="Ana", username="@ana", event_id="evt-1")
    )
    body = bot.send_message.await_args.kwargs["text"]
    assert "Ana @ana" in body
    assert "Ana @@ana" not in body


@pytest.mark.asyncio
async def test_notify_link_without_username_shows_display_name_only() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=7))
    notifier = AiogramOwnerNotifier(bot, owner_telegram_id=999)
    await notifier.notify_link(
        LinkNotification(display_name="Ana", username=None, event_id="evt-1")
    )
    kwargs = bot.send_message.await_args.kwargs
    body = kwargs["text"]
    assert "Ana" in body
    assert "@" not in body

