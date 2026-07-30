"""Data pause toggle keyboard, duration picker, callback sizing, and handler tests."""

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
    menu_pause_duration_keyboard,
    menu_vip_detail_keyboard,
    parse_menu_callback,
)


# ---------------------------------------------------------------------------
# Keyboard rendering
# ---------------------------------------------------------------------------


def test_keyboard_shows_pausar_when_not_paused() -> None:
    kb = menu_vip_detail_keyboard(123, is_paused=False)
    rows = kb.inline_keyboard
    toggle_row = rows[5]
    assert len(toggle_row) == 1
    btn = toggle_row[0]
    assert btn.text == "\U0001f512 Pausar"
    assert "pause" in btn.callback_data


def test_keyboard_shows_reanudar_when_paused() -> None:
    kb = menu_vip_detail_keyboard(123, is_paused=True)
    rows = kb.inline_keyboard
    toggle_row = rows[5]
    assert len(toggle_row) == 1
    btn = toggle_row[0]
    assert btn.text == "\U0001f513 Reanudar"
    assert "unpause" in btn.callback_data


def test_keyboard_backward_compat_no_is_frozen() -> None:
    kb = menu_vip_detail_keyboard(123)
    rows = kb.inline_keyboard
    toggle_row = rows[5]
    btn = toggle_row[0]
    assert btn.text == "\U0001f512 Pausar"


def test_pause_duration_keyboard_has_six_buttons() -> None:
    kb = menu_pause_duration_keyboard(123)
    rows = kb.inline_keyboard
    assert len(rows) == 6
    labels = [r[0].text for r in rows]
    assert "\U0001f4c5 1 dia" in labels
    assert "\U0001f4c5 1 semana" in labels
    assert "\U0001f4c5 3 dias" in labels
    assert "\U0001f4c5 1 mes" in labels
    assert "♾️ Indefinido" in labels
    assert "\U0001f519 Volver al perfil" in labels


# ---------------------------------------------------------------------------
# Callback data size (64-byte limit)
# ---------------------------------------------------------------------------


def test_pause_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "pause")
    assert len(data.encode("utf-8")) <= 64


def test_unpause_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "unpause")
    assert len(data.encode("utf-8")) <= 64


def test_pause_1d_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "pause:1d")
    assert len(data.encode("utf-8")) <= 64


def test_pause_7d_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "pause:7d")
    assert len(data.encode("utf-8")) <= 64


def test_pause_3d_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "pause:3d")
    assert len(data.encode("utf-8")) <= 64


def test_pause_1m_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "pause:1m")
    assert len(data.encode("utf-8")) <= 64


def test_pause_indef_callback_data_under_64_bytes() -> None:
    data = encode_menu_vip_action(2147483647, "pause:indef")
    assert len(data.encode("utf-8")) <= 64


# ---------------------------------------------------------------------------
# Handler logic
# ---------------------------------------------------------------------------


_OWNER_ID = 999


def _callback(
    category: str, action: str | None = None, vip_user_id: int | None = None, extra: str | None = None
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
async def test_pause_without_duration_shows_picker() -> None:
    """Pause action without extra shows the duration picker keyboard."""
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=123),
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
async def test_pause_with_1d_duration() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=123, extra="1d"),
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
    assert vip.paused_until is not None
    delta = vip.paused_until - datetime.now(UTC)
    assert timedelta(hours=23) < delta < timedelta(days=1, hours=1)


@pytest.mark.asyncio
async def test_pause_with_3d_duration() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=123, extra="3d"),
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
    assert vip.paused_until is not None
    delta = vip.paused_until - datetime.now(UTC)
    assert timedelta(days=2, hours=23) < delta < timedelta(days=3, hours=1)


@pytest.mark.asyncio
async def test_pause_with_1m_duration() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=123, extra="1m"),
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
    assert vip.paused_until is not None
    delta = vip.paused_until - datetime.now(UTC)
    assert timedelta(days=29, hours=23) < delta < timedelta(days=30, hours=1)


@pytest.mark.asyncio
async def test_pause_with_7d_duration() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=123, extra="7d"),
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
    assert vip.paused_until is not None
    delta = vip.paused_until - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


@pytest.mark.asyncio
async def test_pause_with_indef_duration() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=123, extra="indef"),
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
    assert vip.paused_until is not None
    assert vip.paused_until.year == 2099


@pytest.mark.asyncio
async def test_unpause_handler_calls_unpause_vip_with_uuid() -> None:
    vips = InMemoryVipStore()
    rec = await vips.add(123, display_name="VIP Test")
    await vips.pause_vip(rec.id, datetime(2099, 12, 31, tzinfo=UTC))
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "unpause", vip_user_id=123),
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
    assert vip.paused_until is None


@pytest.mark.asyncio
async def test_pause_handler_vip_not_found_shows_error() -> None:
    vips = InMemoryVipStore()
    sessions = MenuSessionStore()
    msg = _msg()

    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=99999, extra="indef"),
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
async def test_unpause_handler_vip_not_found_shows_error() -> None:
    vips = InMemoryVipStore()
    sessions = MenuSessionStore()
    msg = _msg()

    await _dispatch_action(
        msg,
        parsed=_callback("vip", "unpause", vip_user_id=99999),
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


def test_pause_duration_keyboard_callback_data() -> None:
    """Each pause duration button has correct callback_data."""
    kb = menu_pause_duration_keyboard(123)
    rows = kb.inline_keyboard
    assert len(rows) == 6
    assert rows[0][0].callback_data == "m:vip:123:pause:1d"
    assert rows[1][0].callback_data == "m:vip:123:pause:7d"
    assert rows[2][0].callback_data == "m:vip:123:pause:3d"
    assert rows[3][0].callback_data == "m:vip:123:pause:1m"
    assert rows[4][0].callback_data == "m:vip:123:pause:indef"
    assert rows[5][0].callback_data == "m:vip:123"


@pytest.mark.asyncio
async def test_pause_handler_vip_inactive_shows_error() -> None:
    vips = InMemoryVipStore()
    await vips.add(123)
    await vips.deactivate(123)
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=123, extra="indef"),
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
async def test_unpause_handler_vip_inactive_shows_error() -> None:
    vips = InMemoryVipStore()
    await vips.add(123)
    await vips.deactivate(123)
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "unpause", vip_user_id=123),
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
async def test_pause_handler_vip_not_found_at_picker_step() -> None:
    """Pause without extra (duration picker step) for a non-existent VIP shows error."""
    vips = InMemoryVipStore()
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=99999),
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
async def test_pause_with_unknown_duration_shows_error() -> None:
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "pause", vip_user_id=123, extra="xyz"),
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
        ("m:vip:123:pause", "vip", "pause", 123, None),
        ("m:vip:123:pause:1d", "vip", "pause", 123, "1d"),
        ("m:vip:123:pause:3d", "vip", "pause", 123, "3d"),
        ("m:vip:123:pause:7d", "vip", "pause", 123, "7d"),
        ("m:vip:123:pause:1m", "vip", "pause", 123, "1m"),
        ("m:vip:123:pause:indef", "vip", "pause", 123, "indef"),
        ("m:vip:123:unpause", "vip", "unpause", 123, None),
    ],
)
def test_parse_menu_callback_pause_variants(
    data: str,
    expected_category: str,
    expected_action: str,
    expected_vip_user_id: int,
    expected_extra: str | None,
) -> None:
    """parse_menu_callback correctly parses all pause/unpause callback variants."""
    result = parse_menu_callback(data)
    assert result is not None
    assert result.category == expected_category
    assert result.action == expected_action
    assert result.vip_user_id == expected_vip_user_id
    assert result.extra == expected_extra


# ---------------------------------------------------------------------------
# Training mode / config menu tests
# ---------------------------------------------------------------------------


class _TrainingModeStore:
    """In-memory TrainingModeStore protocol mock (no DB)."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    async def is_enabled(self) -> bool:
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled


def test_menu_root_has_config_button() -> None:
    """The root menu has 6 buttons; the 6th is Configuracion."""
    from diana.telegram.keyboards import menu_root_keyboard

    kb = menu_root_keyboard()
    rows = kb.inline_keyboard
    assert len(rows) == 6
    config_btn = rows[5][0]
    assert config_btn.text == "⚙️ Configuración"
    assert config_btn.callback_data == "m:config"


@pytest.mark.asyncio
async def test_config_toggle_activates_training_mode() -> None:
    """Toggle with current=False calls set_enabled(True) and shows ON."""
    config_store = _TrainingModeStore(enabled=False)
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("config", "toggle"),
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=MenuSessionStore(),
        config_store=config_store,
    )
    assert config_store._enabled is True
    call_args = msg.edit_text.call_args
    assert call_args is not None
    # Should show the toggle keyboard with ON state
    rendered = call_args[1].get("reply_markup")
    assert rendered is not None
    # The toggle button text should indicate ON
    toggle_row = rendered.inline_keyboard[0]
    assert "ON" in toggle_row[0].text


@pytest.mark.asyncio
async def test_config_toggle_deactivates_training_mode() -> None:
    """Toggle with current=True calls set_enabled(False) and shows OFF."""
    config_store = _TrainingModeStore(enabled=True)
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("config", "toggle"),
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=MenuSessionStore(),
        config_store=config_store,
    )
    assert config_store._enabled is False
    call_args = msg.edit_text.call_args
    assert call_args is not None
    rendered = call_args[1].get("reply_markup")
    assert rendered is not None
    toggle_row = rendered.inline_keyboard[0]
    assert "OFF" in toggle_row[0].text


@pytest.mark.asyncio
async def test_config_toggle_no_config_store_shows_unavailable() -> None:
    """Toggle with config_store=None shows 'no disponible'."""
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("config", "toggle"),
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=MenuSessionStore(),
        config_store=None,
    )
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "no disponible" in call_args[0][0].lower()
