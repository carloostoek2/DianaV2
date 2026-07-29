"""Freeze toggle keyboard, duration picker, callback sizing, and handler tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, User

from diana.application.memory import InMemoryVipStore
from diana.application.ports import VipRecord
from diana.telegram.handlers.menu import _dispatch_action, MenuSessionStore
from diana.telegram.keyboards import (
    MenuCallback,
    encode_menu_vip_action,
    menu_freeze_duration_keyboard,
    menu_vip_detail_keyboard,
    parse_menu_callback,
)


# ---------------------------------------------------------------------------
# Keyboard rendering
# ---------------------------------------------------------------------------


def test_keyboard_shows_pausar_when_not_frozen() -> None:
    kb = menu_vip_detail_keyboard(123, is_frozen=False)
    rows = kb.inline_keyboard
    toggle_row = rows[5]
    assert len(toggle_row) == 1
    btn = toggle_row[0]
    assert btn.text == "\U0001f512 Pausar"
    assert "freeze" in btn.callback_data


def test_keyboard_shows_reanudar_when_frozen() -> None:
    kb = menu_vip_detail_keyboard(123, is_frozen=True)
    rows = kb.inline_keyboard
    toggle_row = rows[5]
    assert len(toggle_row) == 1
    btn = toggle_row[0]
    assert btn.text == "\U0001f513 Reanudar"
    assert "unfreeze" in btn.callback_data


def test_keyboard_backward_compat_no_is_frozen() -> None:
    kb = menu_vip_detail_keyboard(123)
    rows = kb.inline_keyboard
    toggle_row = rows[5]
    btn = toggle_row[0]
    assert btn.text == "\U0001f512 Pausar"


def test_freeze_duration_keyboard_has_four_buttons() -> None:
    kb = menu_freeze_duration_keyboard(123)
    rows = kb.inline_keyboard
    assert len(rows) == 4
    labels = [r[0].text for r in rows]
    assert "\U0001f4c5 1 dia" in labels
    assert "\U0001f4c5 1 semana" in labels
    assert "♾️ Indefinido" in labels
    assert "\U0001f519 Volver al perfil" in labels


# ---------------------------------------------------------------------------
# Callback data size (64-byte limit)
# ---------------------------------------------------------------------------


def test_freeze_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "freeze")
    assert len(data.encode("utf-8")) <= 64


def test_unfreeze_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "unfreeze")
    assert len(data.encode("utf-8")) <= 64


def test_freeze_1d_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "freeze:1d")
    assert len(data.encode("utf-8")) <= 64


def test_freeze_7d_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "freeze:7d")
    assert len(data.encode("utf-8")) <= 64


def test_freeze_indef_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "freeze:indef")
    assert len(data.encode("utf-8")) <= 64


# ---------------------------------------------------------------------------
# Handler logic
# ---------------------------------------------------------------------------


_OWNER_ID = 999


def _callback(
    category: str, action: str, vip_user_id: int | None = None, extra: str | None = None
):
    from diana.telegram.keyboards import MenuCallback

    return MenuCallback(
        category=category, action=action, vip_user_id=vip_user_id or 0, extra=extra
    )


def _msg(user_id: int = _OWNER_ID) -> AsyncMock:
    msg = AsyncMock(spec=Message)
    msg.message_id = 1
    msg.chat = AsyncMock(spec=Chat)
    msg.chat.id = 42
    msg.edit_text = AsyncMock()
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_freeze_without_duration_shows_picker() -> None:
    """Freeze action without extra shows the duration picker keyboard."""
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "freeze", vip_user_id=123),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )

    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "Pausar" in call_args[0][0]
    assert "duracion" in call_args[0][0]


@pytest.mark.asyncio
async def test_freeze_with_1d_duration() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "freeze", vip_user_id=123, extra="1d"),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )

    vip = await vips.get_by_telegram_user_id(123)
    assert vip is not None
    assert vip.frozen_until is not None
    delta = vip.frozen_until - datetime.now(UTC)
    assert timedelta(hours=23) < delta < timedelta(days=1, hours=1)


@pytest.mark.asyncio
async def test_freeze_with_7d_duration() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "freeze", vip_user_id=123, extra="7d"),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )

    vip = await vips.get_by_telegram_user_id(123)
    assert vip is not None
    assert vip.frozen_until is not None
    delta = vip.frozen_until - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


@pytest.mark.asyncio
async def test_freeze_with_indef_duration() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "freeze", vip_user_id=123, extra="indef"),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )

    vip = await vips.get_by_telegram_user_id(123)
    assert vip is not None
    assert vip.frozen_until is not None
    assert vip.frozen_until.year == 2099


@pytest.mark.asyncio
async def test_unfreeze_handler_calls_unfreeze_vip_with_uuid() -> None:
    vips = InMemoryVipStore()
    rec = await vips.add(123, display_name="VIP Test")
    await vips.freeze_vip(rec.id, datetime(2099, 12, 31, tzinfo=UTC))
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "unfreeze", vip_user_id=123),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )

    vip = await vips.get_by_telegram_user_id(123)
    assert vip is not None
    assert vip.frozen_until is None


@pytest.mark.asyncio
async def test_freeze_handler_vip_not_found_shows_error() -> None:
    vips = InMemoryVipStore()
    sessions = MenuSessionStore()
    msg = _msg()

    await _dispatch_action(
        msg,
        parsed=_callback("vip", "freeze", vip_user_id=99999, extra="indef"),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )

    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "no encontrado" in call_args[0][0] or "inactivo" in call_args[0][0]


@pytest.mark.asyncio
async def test_unfreeze_handler_vip_not_found_shows_error() -> None:
    vips = InMemoryVipStore()
    sessions = MenuSessionStore()
    msg = _msg()

    await _dispatch_action(
        msg,
        parsed=_callback("vip", "unfreeze", vip_user_id=99999),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )

    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "no encontrado" in call_args[0][0] or "inactivo" in call_args[0][0]


def test_freeze_duration_keyboard_callback_data() -> None:
    """Each freeze duration button has correct callback_data."""
    kb = menu_freeze_duration_keyboard(123)
    rows = kb.inline_keyboard
    assert len(rows) == 4
    assert rows[0][0].callback_data == "m:vip:123:freeze:1d"
    assert rows[1][0].callback_data == "m:vip:123:freeze:7d"
    assert rows[2][0].callback_data == "m:vip:123:freeze:indef"
    assert rows[3][0].callback_data == "m:vip:123"


@pytest.mark.asyncio
async def test_freeze_handler_vip_inactive_shows_error() -> None:
    vips = InMemoryVipStore()
    await vips.add(123)
    await vips.deactivate(123)
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "freeze", vip_user_id=123, extra="indef"),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "no encontrado" in call_args[0][0] or "inactivo" in call_args[0][0]


@pytest.mark.asyncio
async def test_unfreeze_handler_vip_inactive_shows_error() -> None:
    vips = InMemoryVipStore()
    await vips.add(123)
    await vips.deactivate(123)
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "unfreeze", vip_user_id=123),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "no encontrado" in call_args[0][0] or "inactivo" in call_args[0][0]


@pytest.mark.asyncio
async def test_freeze_handler_vip_not_found_at_picker_step() -> None:
    """Freeze without extra (duration picker step) for a non-existent VIP shows error."""
    vips = InMemoryVipStore()
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "freeze", vip_user_id=99999),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "no encontrado" in call_args[0][0] or "inactivo" in call_args[0][0]


@pytest.mark.asyncio
async def test_freeze_with_unknown_duration_shows_error() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "freeze", vip_user_id=123, extra="xyz"),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "valida" in call_args[0][0]


@pytest.mark.parametrize(
    "data,expected_category,expected_action,expected_vip_user_id,expected_extra",
    [
        ("m:vip:123:freeze", "vip", "freeze", 123, None),
        ("m:vip:123:freeze:1d", "vip", "freeze", 123, "1d"),
        ("m:vip:123:freeze:7d", "vip", "freeze", 123, "7d"),
        ("m:vip:123:freeze:indef", "vip", "freeze", 123, "indef"),
        ("m:vip:123:unfreeze", "vip", "unfreeze", 123, None),
    ],
)
def test_parse_menu_callback_freeze_variants(
    data: str,
    expected_category: str,
    expected_action: str,
    expected_vip_user_id: int,
    expected_extra: str | None,
) -> None:
    """parse_menu_callback correctly parses all freeze/unfreeze callback variants."""
    result = parse_menu_callback(data)
    assert result is not None
    assert result.category == expected_category
    assert result.action == expected_action
    assert result.vip_user_id == expected_vip_user_id
    assert result.extra == expected_extra
