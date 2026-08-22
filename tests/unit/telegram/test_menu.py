"""Data pause toggle keyboard, duration picker, callback sizing, and handler tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, User

from diana.application.memory import InMemoryVipStore
from diana.application.ports import VipRecord
from diana.application.profile_admin_service import ProfileAdminResult
from diana.telegram.handlers.menu import (
    HasActiveMenuSession,
    MenuSessionStore,
    _dispatch_action,
    _format_vip_profile,
    _handle_note_text,
    _handle_sandbox_forward,
    build_menu_router,
)
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
    assert "\U0001f4c5 1 día" in labels
    assert "\U0001f4c5 1 semana" in labels
    assert "\U0001f4c5 3 días" in labels
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
    assert "duración" in call_args[0][0]


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
    """The root menu has 8 buttons; the last is Configuracion."""
    from diana.telegram.keyboards import menu_root_keyboard

    kb = menu_root_keyboard()
    rows = kb.inline_keyboard
    assert len(rows) == 8
    config_btn = rows[7][0]
    assert config_btn.text == "⚙️ Configuración"
    assert config_btn.callback_data == "m:config"
    # Eventos temporales sits between Historial and Configuración.
    event_btn = rows[5][0]
    assert event_btn.callback_data == "m:event"
    # Modo sombra sits between Eventos and Configuración.
    shadow_btn = rows[6][0]
    assert shadow_btn.text == "🤖 Modo sombra"
    assert shadow_btn.callback_data == "m:sombra"


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


# ---------------------------------------------------------------------------
# F5 Pool 2 — profile generation from the ficha (REQ-MEM-05)
# ---------------------------------------------------------------------------


class _BackfillQueueFake:
    """Minimal schedule_enqueue spy (fire-and-forget contract)."""

    def __init__(self) -> None:
        self.scheduled: list[int] = []

    def schedule_enqueue(self, telegram_user_id: int, **_: object) -> None:
        self.scheduled.append(telegram_user_id)


@pytest.mark.asyncio
async def test_profile_generate_enqueues_backfill() -> None:
    """'Generar perfil' from the ficha enqueues the VIP and acks without blocking."""
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    queue = _BackfillQueueFake()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "profile_generate", vip_user_id=123),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=MenuSessionStore(),
        backfill_queue=queue,
    )
    assert queue.scheduled == [123]
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "en cola" in call_args[0][0].lower()


@pytest.mark.asyncio
async def test_profile_generate_unavailable_without_queue() -> None:
    """Flag OFF (queue=None): the action shows 'no disponible', nothing enqueued."""
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "profile_generate", vip_user_id=123),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=MenuSessionStore(),
        backfill_queue=None,
    )
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "no disponible" in call_args[0][0].lower()


@pytest.mark.asyncio
async def test_register_confirm_enqueues_backfill() -> None:
    """Registering a new VIP from the panel also enqueues its profile backfill."""
    queue = _BackfillQueueFake()
    sessions = MenuSessionStore()
    # A7: the confirm only executes while its confirmation prompt is live.
    sessions.record_confirmation(_OWNER_ID)

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("register", "confirm", extra="777"),
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
        backfill_queue=queue,
    )
    assert queue.scheduled == [777]


@pytest.mark.asyncio
async def test_register_confirm_expired_is_rejected() -> None:
    """A7: a Confirm tap without a live confirmation must not register the VIP."""
    queue = _BackfillQueueFake()
    sessions = MenuSessionStore()

    msg = _msg()
    result = await _dispatch_action(
        msg,
        parsed=_callback("register", "confirm", extra="777"),
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
        backfill_queue=queue,
    )
    assert result == "confirm_expired"
    assert queue.scheduled == []
    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "expiró" in call_args[0][0]


@pytest.mark.asyncio
async def test_delete_confirm_expired_is_rejected() -> None:
    """A7: a stale delete-confirm button must not deactivate the VIP."""
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    result = await _dispatch_action(
        msg,
        parsed=_callback("vip", "delete_confirm", vip_user_id=123),
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
    assert result == "confirm_expired"
    assert await vips.get_by_telegram_user_id(123) is not None


def test_profile_keyboard_show_generate_button() -> None:
    """The ficha keyboard shows 'Generar perfil' only when the queue is wired."""
    from diana.telegram.keyboards import menu_vip_profile_keyboard

    with_generate = menu_vip_profile_keyboard(123, show_generate=True)
    texts = [b.text for row in with_generate.inline_keyboard for b in row]
    assert any("Generar perfil" in t for t in texts)

    default = menu_vip_profile_keyboard(123)
    default_texts = [b.text for row in default.inline_keyboard for b in row]
    assert not any("Generar perfil" in t for t in default_texts)


def test_profile_keyboard_per_item_delete_buttons() -> None:
    """The ficha keyboard lists one delete button per fact and note (A9)."""
    from diana.telegram.keyboards import menu_vip_profile_keyboard

    kb = menu_vip_profile_keyboard(
        123,
        facts={"city": "BA", "age": "28"},
        notes=["nota uno", "nota dos"],
    )
    texts = [b.text for row in kb.inline_keyboard for b in row]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "🗑 city" in texts
    assert "🗑 age" in texts
    assert "🗑 Nota 1" in texts
    assert "🗑 Nota 2" in texts
    assert "m:vip:123:fact_del:city" in callbacks
    assert "m:vip:123:fact_del:age" in callbacks
    assert "m:vip:123:note_del:1" in callbacks
    assert "m:vip:123:note_del:2" in callbacks
    assert "🔙 Volver al perfil" in texts
    assert "🔙 Inicio" in texts


def test_profile_keyboard_no_delete_buttons_without_data() -> None:
    """No facts/notes -> only back navigation, no delete rows (A9)."""
    from diana.telegram.keyboards import menu_vip_profile_keyboard

    kb = menu_vip_profile_keyboard(123)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert all("🗑" not in t for t in texts)


def test_profile_keyboard_skips_overlong_fact_key() -> None:
    """A fact key too long for callback_data is skipped, not crashed (A9)."""
    from diana.telegram.keyboards import menu_vip_profile_keyboard

    long_key = "k" * 80
    kb = menu_vip_profile_keyboard(123, facts={long_key: "v", "city": "BA"})
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "🗑 city" in texts
    assert all(f"🗑 {long_key}" not in t for t in texts)


def _fake_profile_admin(*, content: dict | None = None) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        show_profile=AsyncMock(
            return_value=ProfileAdminResult(
                status="profile_ok",
                telegram_user_id=123,
                display_name="VIP Test",
                content=content,
            )
        ),
    )


@pytest.mark.asyncio
async def test_profile_action_shows_delete_buttons_per_item() -> None:
    """Viewing a ficha with facts/notes shows the per-item delete buttons (A9)."""
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()
    profile_admin = _fake_profile_admin(
        content={"facts": {"city": "BA"}, "notes": ["nota uno"]}
    )

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "profile", vip_user_id=123),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=profile_admin,
        sessions=sessions,
    )

    call_args = msg.edit_text.call_args
    assert call_args is not None
    kb = call_args[1]["reply_markup"]
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "🗑 city" in texts
    assert "🗑 Nota 1" in texts


@pytest.mark.asyncio
async def test_note_del_from_ficha_deletes_note() -> None:
    """The per-item note button deletes that note index and reports back (A9)."""
    from types import SimpleNamespace

    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()
    profile_admin = SimpleNamespace(
        delete_note=AsyncMock(
            return_value=ProfileAdminResult(
                status="note_deleted",
                telegram_user_id=123,
                display_name="VIP Test",
                detail="2",
            )
        ),
    )

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "note_del", vip_user_id=123, extra="2"),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=profile_admin,
        sessions=sessions,
    )

    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "Nota 2 eliminada" in call_args[0][0]
    profile_admin.delete_note.assert_awaited_once_with(_OWNER_ID, 123, 2)


@pytest.mark.asyncio
async def test_fact_del_from_ficha_deletes_fact() -> None:
    """The per-item fact button deletes that fact key and reports back (A9)."""
    from types import SimpleNamespace

    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()
    profile_admin = SimpleNamespace(
        delete_fact=AsyncMock(
            return_value=ProfileAdminResult(
                status="fact_deleted",
                telegram_user_id=123,
                display_name="VIP Test",
            )
        ),
    )

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "fact_del", vip_user_id=123, extra="city"),
        actor_id=_OWNER_ID,
        vips=vips,
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=profile_admin,
        sessions=sessions,
    )

    call_args = msg.edit_text.call_args
    assert call_args is not None
    assert "Dato 'city' eliminado" in call_args[0][0]
    profile_admin.delete_fact.assert_awaited_once_with(_OWNER_ID, 123, "city")


@pytest.mark.asyncio
async def test_stale_vip_button_redirects_to_list_when_deactivated() -> None:
    """A stale m:vip card button for a deactivated VIP redirects to the list (A13)."""
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    await vips.deactivate(123)
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "123", vip_user_id=123),
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
    assert "ya no existe o fue desactivado" in call_args[0][0]
    kb = call_args[1]["reply_markup"]
    back_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "m:vips" in back_data


@pytest.mark.asyncio
async def test_active_vip_card_still_shows_actions() -> None:
    """An active VIP still gets the detail card with its actions (A13 guard)."""
    vips = InMemoryVipStore()
    await vips.add(123, display_name="VIP Test")
    sessions = MenuSessionStore()

    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "123", vip_user_id=123),
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
    assert "Perfil de VIP Test" in call_args[0][0]
    assert "Selecciona una acción:" in call_args[0][0]
    kb = call_args[1]["reply_markup"]
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Pausar" in t or "Reanudar" in t for t in texts)


# --- F5 Pool 4 (F5-06): 🧠 Memoria section of the ficha ---


def test_format_vip_profile_renders_memory_section() -> None:
    """The ficha shows the memory section with per-fact status icons and the
    /memoria hint when pending facts exist."""
    result = ProfileAdminResult(
        status="profile_ok",
        telegram_user_id=555,
        display_name="Alice",
        content={"facts": {"city": "BA"}, "notes": []},
        memory=[
            {
                "category": "preferencias",
                "status": "auto",
                "content": {"texto": "Le gusta viajar"},
            },
            {
                "category": "sensible",
                "status": "pending_owner",
                "content": {"texto": "Mencionó su salud"},
            },
        ],
    )

    text = _format_vip_profile(result)

    assert "🧠 Memoria" in text
    assert "[preferencias] Le gusta viajar" in text
    assert "⏳ pendiente" in text
    assert "Hay 1 hechos por aprobar — usa /memoria." in text
    # Manual ficha still present (section added, not replaced).
    assert "📌 Datos:" in text
    assert "city: BA" in text


def test_format_vip_profile_empty_manual_with_memory() -> None:
    """The diagnosed 'perfil generado pero no se ve nada' case: empty manual
    ficha + memory present → the ficha renders the memory, NOT 'Sin datos'."""
    result = ProfileAdminResult(
        status="profile_empty",
        telegram_user_id=555,
        display_name="Alice",
        content=None,
        memory=[
            {
                "category": "preferencias",
                "status": "approved",
                "content": {"texto": "Le gusta viajar"},
            }
        ],
    )

    text = _format_vip_profile(result)

    assert "🧠 Memoria" in text
    assert "Le gusta viajar" in text
    assert "Sin datos" not in text


def test_format_vip_profile_empty_without_memory_stays_empty_card() -> None:
    """No manual data AND no memory → the 'Sin datos todavia' card remains."""
    result = ProfileAdminResult(
        status="profile_empty",
        telegram_user_id=555,
        display_name="Alice",
        content=None,
        memory=None,
    )

    text = _format_vip_profile(result)

    assert "Sin datos" in text
    assert "🧠 Memoria" not in text


# --- Evo-Agente Fase 5 (EA-06): 🔐 Confianza section of the ficha ------------


def test_format_vip_profile_renders_trust_section() -> None:
    """The ficha shows the trust section with per-category score, trend icon,
    counts and last-correction date (additive, memory section untouched)."""
    result = ProfileAdminResult(
        status="profile_ok",
        telegram_user_id=555,
        display_name="Alice",
        content={"facts": {"city": "BA"}, "notes": []},
        trust_budget=[
            {
                "category": "fatico",
                "trust_score": 0.42,
                "autonomous_count": 3,
                "correction_count": 1,
                "last_correction_at": "2026-08-05T10:00:00+00:00",
                "trend": "down",
            }
        ],
    )

    text = _format_vip_profile(result)

    assert "🔐 Confianza" in text
    assert "[fatico] 0.42 ▼" in text
    assert "autónomos 3" in text
    assert "correcciones 1" in text
    assert "última 2026-08-05" in text
    # Memory/manual sections untouched.
    assert "📌 Datos:" in text
    assert "city: BA" in text


def test_format_vip_profile_empty_with_trust_shows_trust() -> None:
    """No manual ficha + no memory, but trust rows → the ficha shows the 🔐
    section, NOT the 'Sin datos' empty card."""
    result = ProfileAdminResult(
        status="profile_empty",
        telegram_user_id=555,
        display_name="Alice",
        trust_budget=[
            {
                "category": "informativo",
                "trust_score": 0.9,
                "autonomous_count": 2,
                "correction_count": 0,
                "last_correction_at": None,
                "trend": "up",
            }
        ],
    )

    text = _format_vip_profile(result)

    assert "🔐 Confianza" in text
    assert "[informativo] 0.90 ▲" in text
    assert "Sin datos" not in text


def test_format_vip_profile_no_trust_no_section() -> None:
    """trust_budget None/[] → no orphan 🔐 header, memory hint still works."""
    result = ProfileAdminResult(
        status="profile_ok",
        telegram_user_id=555,
        display_name="Alice",
        content={"facts": {"city": "BA"}, "notes": []},
        trust_budget=None,
    )

    text = _format_vip_profile(result)

    assert "🔐 Confianza" not in text
    assert "📌 Datos:" in text

    empty_rows = ProfileAdminResult(
        status="profile_ok",
        telegram_user_id=555,
        display_name="Alice",
        content={"facts": {"city": "BA"}, "notes": []},
        trust_budget=[],
    )
    assert "🔐 Confianza" not in _format_vip_profile(empty_rows)


# ---------------------------------------------------------------------------
# A2 — wizards survive invalid input (session stays alive to retry)
# ---------------------------------------------------------------------------


def _text_msg(text: str, *, forward_origin: object = None) -> AsyncMock:
    msg = AsyncMock(spec=Message)
    msg.message_id = 1
    msg.chat = AsyncMock(spec=Chat)
    msg.chat.id = 42
    msg.text = text
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    msg.answer = AsyncMock()
    msg.forward_origin = forward_origin
    msg.forward_from_chat = None
    msg.forward_from = None
    return msg


def _bot() -> AsyncMock:
    bot = AsyncMock()
    bot.edit_message_text = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_note_text_empty_keeps_wizard_alive() -> None:
    """A2: an empty note must NOT kill the wizard — the next text still lands here."""
    profile_admin = AsyncMock()
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "note", vip_user_id=777, last_bot_message_id=1, last_chat_id=42)
    session = sessions.pop(_OWNER_ID)  # mirror on_menu_session_text
    assert session is not None

    await _handle_note_text(_text_msg("  "), _bot(), session, profile_admin, sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None
    assert retry.kind == "note"
    assert retry.vip_user_id == 777


@pytest.mark.asyncio
async def test_note_text_invalid_forward_keeps_sandbox_wizard_alive() -> None:
    """A2: a non-forward during sandbox_forward must keep the wizard alive."""
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "sandbox_forward", last_bot_message_id=1, last_chat_id=42)
    session = sessions.pop(_OWNER_ID)
    assert session is not None

    await _handle_sandbox_forward(_text_msg("hola"), _bot(), session, AsyncMock(), sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None
    assert retry.kind == "sandbox_forward"


@pytest.mark.asyncio
async def test_has_active_menu_session_skips_commands() -> None:
    """A2: a slash-command during an active session routes to its own handler."""
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "note", vip_user_id=777)
    filt = HasActiveMenuSession(sessions)

    assert await filt(_text_msg("/list_vips")) is False
    assert await filt(_text_msg("texto normal")) is True


@pytest.mark.asyncio
async def test_has_active_menu_session_matches_forwarded_command() -> None:
    """A forward whose content starts with '/' still reaches the wizard."""
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "sandbox_forward")
    filt = HasActiveMenuSession(sessions)

    assert await filt(_text_msg("/start", forward_origin=object())) is True


# --- A7: destructive-confirmation TTL (delete/register) ---


def test_confirmation_live_until_consumed() -> None:
    sessions = MenuSessionStore()
    assert sessions.confirmation_live(_OWNER_ID) is False
    sessions.record_confirmation(_OWNER_ID)
    assert sessions.confirmation_live(_OWNER_ID) is True
    assert sessions.consume_confirmation(_OWNER_ID) is True
    assert sessions.confirmation_live(_OWNER_ID) is False


def test_confirmation_expires_by_ttl() -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    state = {"now": now}
    sessions = MenuSessionStore(clock=lambda: state["now"])
    sessions.record_confirmation(_OWNER_ID)
    assert sessions.confirmation_live(_OWNER_ID) is True
    state["now"] = now + timedelta(minutes=16)  # past the 15-min TTL
    assert sessions.confirmation_live(_OWNER_ID) is False
    assert sessions.consume_confirmation(_OWNER_ID) is False


def test_confirmation_is_not_tied_to_active_menu_session() -> None:
    """A pending confirmation must not make HasActiveMenuSession match text."""
    sessions = MenuSessionStore()
    sessions.record_confirmation(_OWNER_ID)
    assert sessions.has_active(_OWNER_ID) is False


# --- A5: no error leaves the owner without a back button ---


def _rendered_keyboard(msg: AsyncMock):
    call = msg.edit_text.await_args
    assert call is not None
    return call[1].get("reply_markup")


@pytest.mark.asyncio
async def test_profile_unavailable_has_back_keyboard() -> None:
    """A5: 'Gestion de perfiles no disponible' offers a back button."""
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("vip", "profile", vip_user_id=123),
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,  # triggers the unavailable branch
        sessions=MenuSessionStore(),
    )
    assert "no disponible" in msg.edit_text.await_args[0][0].lower()
    assert _rendered_keyboard(msg) is not None


@pytest.mark.asyncio
async def test_register_invalid_id_has_back_keyboard() -> None:
    """A5: 'ID de usuario inválido' offers a back button to the VIPs menu."""
    sessions = MenuSessionStore()
    sessions.record_confirmation(_OWNER_ID)  # A7: confirmation must be live
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("register", "confirm", extra="abc"),  # not an int
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
    )
    assert "inválido" in msg.edit_text.await_args[0][0]
    assert _rendered_keyboard(msg) is not None


class _NoActiveSandbox:
    def get_focus_chat_id(self) -> None:
        return None


@pytest.mark.asyncio
async def test_sandbox_off_no_active_has_back_keyboard() -> None:
    """A5: 'No hay modo de prueba activo' offers a back button to sandbox."""
    msg = _msg()
    await _dispatch_action(
        msg,
        parsed=_callback("sandbox", "off"),
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=_NoActiveSandbox(),
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=MenuSessionStore(),
    )
    assert "No hay modo de prueba activo" in msg.edit_text.await_args[0][0]
    assert _rendered_keyboard(msg) is not None


# --- A6: a wizard that expired must warn, not swallow the input ---


def test_session_status_none_live_expired() -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    state = {"now": now}
    sessions = MenuSessionStore(clock=lambda: state["now"])
    assert sessions.status(_OWNER_ID) == "none"
    sessions.start(_OWNER_ID, "note", vip_user_id=777)
    assert sessions.status(_OWNER_ID) == "live"
    state["now"] = now + timedelta(minutes=16)  # past the 15-min TTL
    assert sessions.status(_OWNER_ID) == "expired"
    # status() does not consume; pop() clears the expired entry.
    assert sessions.pop(_OWNER_ID) is None
    assert sessions.status(_OWNER_ID) == "none"


@pytest.mark.asyncio
async def test_has_active_menu_session_matches_expired_for_warning() -> None:
    """A6: expired wizard still routes plain text so the handler can warn."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    state = {"now": now}
    sessions = MenuSessionStore(clock=lambda: state["now"])
    sessions.start(_OWNER_ID, "note", vip_user_id=777)
    filt = HasActiveMenuSession(sessions)
    state["now"] = now + timedelta(minutes=16)
    assert await filt(_text_msg("texto normal")) is True
    # Commands still bypass the expired wizard.
    assert await filt(_text_msg("/list_vips")) is False


@pytest.mark.asyncio
async def test_menu_session_text_expired_warns_and_clears() -> None:
    """A6: writing after the wizard expired replies 'expiró' and clears it."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    state = {"now": now}
    sessions = MenuSessionStore(clock=lambda: state["now"])
    sessions.start(_OWNER_ID, "note", vip_user_id=777)
    router = build_menu_router(
        owner_telegram_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        menu_sessions=sessions,
    )
    handler = None
    for h in router.message.handlers:
        fo = h.filters[0]
        if isinstance(getattr(fo, "callback", None), HasActiveMenuSession):
            handler = h.callback
    assert handler is not None

    state["now"] = now + timedelta(minutes=16)
    msg = _text_msg("nota tardía")
    msg.chat.type = "private"  # satisfy the owner-DM gate
    msg.reply = AsyncMock()
    await handler(msg, _bot())

    msg.reply.assert_awaited_once()
    reply_text = msg.reply.await_args.args[0]
    assert "expiró" in reply_text
    assert sessions.status(_OWNER_ID) == "none"  # expired entry cleaned up


# --- Evo-Agente Fase 5 (EA-06): 📚 Historial de versiones de la ficha ---


def test_format_vip_profile_renders_version_history() -> None:
    """The ficha shows the profile version history with date and diff summary."""
    from diana.application.profile_admin_service import ProfileAdminResult

    result = ProfileAdminResult(
        status="profile_ok",
        telegram_user_id=555,
        display_name="Alice",
        content={"facts": {"city": "CDMX"}, "notes": []},
        profile_history=[
            {
                "version": 3,
                "created_at": "2026-08-22T21:17:00+00:00",
                "diff_summary": "Cliente más cercano, mencionó un viaje",
            },
            {
                "version": 2,
                "created_at": "2026-08-10T12:00:00+00:00",
                "diff_summary": "Nuevo interés: café de especialidad",
            },
        ],
    )

    text = _format_vip_profile(result)

    assert "📚 Historial de versiones" in text
    assert "v3 · 2026-08-22 — Cliente más cercano, mencionó un viaje" in text
    assert "v2 · 2026-08-10 — Nuevo interés: café de especialidad" in text


def test_format_vip_profile_empty_manual_with_history_keeps_card() -> None:
    """A VIP with only version history still gets a ficha (no 'Sin datos')."""
    from diana.application.profile_admin_service import ProfileAdminResult

    result = ProfileAdminResult(
        status="profile_empty",
        telegram_user_id=555,
        display_name="Alice",
        content=None,
        memory=None,
        profile_history=[
            {
                "version": 1,
                "created_at": "2026-08-01T00:00:00+00:00",
                "diff_summary": "Perfil inicial",
            }
        ],
    )

    text = _format_vip_profile(result)

    assert "📚 Historial de versiones" in text
    assert "Sin datos" not in text


def test_format_vip_profile_history_truncates_long_summary() -> None:
    from diana.application.profile_admin_service import ProfileAdminResult

    long_diff = "x" * 200
    result = ProfileAdminResult(
        status="profile_ok",
        telegram_user_id=555,
        display_name="Alice",
        content={"facts": {}, "notes": []},
        profile_history=[
            {"version": 1, "created_at": "2026-08-01T00:00:00+00:00", "diff_summary": long_diff}
        ],
    )

    text = _format_vip_profile(result)

    assert "…" in text
    assert len([l for l in text.splitlines() if l.startswith("  • v1")][0]) < 160
