"""Unit tests for the Eventos temporales owner menu (keyboards + handlers)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import CallbackQuery, Chat, Message

from diana.application.ephemeral_event_service import EphemeralEventService
from diana.application.memory import InMemoryVipStore
from diana.application.ports import EphemeralEventRecord
from diana.telegram.handlers.menu import (
    MenuSessionStore,
    _dispatch_action,
    _handle_event_body_text,
    _handle_event_custom_end_text,
    _handle_event_custom_start_text,
    _handle_event_edit_body_text,
    _render_event_list,
    build_menu_router,
)
from diana.telegram.keyboards import (
    MENU_EVENT_EMPTY_TEXT,
    MENU_EVENT_LIST_TEXT,
    MenuCallback,
    encode_menu,
    encode_menu_event,
    encode_menu_event_action,
    menu_event_detail_keyboard,
    menu_event_duration_keyboard,
    menu_event_list_keyboard,
    parse_menu_callback,
)

_OWNER_ID = 999
_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeEphemeralEventStore:
    """In-memory EphemeralEventStore mirroring the repo's SQL semantics."""

    def __init__(self, events: list[EphemeralEventRecord] | None = None) -> None:
        self._events = list(events or [])

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def create(self, *, body, start_at, end_at, created_by=None) -> EphemeralEventRecord:
        now = self._now()
        rec = EphemeralEventRecord(
            id=uuid4(), body=body, start_at=start_at, end_at=end_at,
            is_paused=False, created_by=created_by, created_at=now, updated_at=now,
        )
        self._events.append(rec)
        return rec

    async def get(self, event_id) -> EphemeralEventRecord | None:
        return next((e for e in self._events if e.id == event_id), None)

    async def list_all(self) -> list[EphemeralEventRecord]:
        return list(self._events)

    async def list_open(self, now: datetime) -> list[EphemeralEventRecord]:
        return [e for e in self._events if e.end_at > now]

    async def update(self, event_id, *, body, start_at, end_at) -> EphemeralEventRecord | None:
        rec = await self.get(event_id)
        if rec is None:
            return None
        updated = rec.model_copy(
            update={"body": body, "start_at": start_at, "end_at": end_at, "updated_at": self._now()}
        )
        self._events = [updated if e.id == event_id else e for e in self._events]
        return updated

    async def set_paused(self, event_id, paused) -> EphemeralEventRecord | None:
        rec = await self.get(event_id)
        if rec is None:
            return None
        updated = rec.model_copy(
            update={"is_paused": paused, "updated_at": self._now()}
        )
        self._events = [updated if e.id == event_id else e for e in self._events]
        return updated

    async def terminate_now(self, event_id, now) -> EphemeralEventRecord | None:
        rec = await self.get(event_id)
        if rec is None:
            return None
        updated = rec.model_copy(update={"end_at": now, "updated_at": self._now()})
        self._events = [updated if e.id == event_id else e for e in self._events]
        return updated

    async def delete(self, event_id) -> bool:
        before = len(self._events)
        self._events = [e for e in self._events if e.id != event_id]
        return len(self._events) < before

    async def find_active_at(self, now: datetime) -> list[EphemeralEventRecord]:
        return [
            e for e in self._events
            if not e.is_paused and e.start_at <= now < e.end_at
        ]


def _event(**kw) -> EphemeralEventRecord:
    data = dict(
        id=uuid4(),
        body="promo del fin de semana",
        start_at=_NOW - timedelta(hours=1),
        end_at=_NOW + timedelta(days=2),
        is_paused=False,
        created_by=_OWNER_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )
    data.update(kw)
    return EphemeralEventRecord(**data)


def _service(store: _FakeEphemeralEventStore) -> EphemeralEventService:
    return EphemeralEventService(
        store=store, owner_telegram_id=_OWNER_ID, clock=lambda: _NOW
    )


def _msg() -> AsyncMock:
    msg = AsyncMock(spec=Message)
    msg.message_id = 1
    msg.chat = AsyncMock(spec=Chat)
    msg.chat.id = 42
    msg.edit_text = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _text_msg(text: str) -> AsyncMock:
    msg = _msg()
    msg.text = text
    msg.from_user = AsyncMock()
    msg.from_user.id = _OWNER_ID
    return msg


def _bot() -> AsyncMock:
    bot = AsyncMock()
    bot.edit_message_text = AsyncMock()
    return bot


def _parsed(
    action: str | None = None, event_id=None, extra: str | None = None
) -> MenuCallback:
    return MenuCallback(category="event", action=action, event_id=event_id, extra=extra)


async def _dispatch(msg, *, action=None, event_id=None, service, sessions, extra=None):
    return await _dispatch_action(
        msg,
        parsed=_parsed(action=action, event_id=event_id, extra=extra),
        actor_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        admin_trace=None,
        admin_metrics=None,
        sandbox=None,
        staging=None,
        coordinator=None,
        profile_admin=None,
        sessions=sessions,
        ephemeral_event_service=service,
    )


def _last_text(msg: AsyncMock) -> str:
    call = msg.edit_text.call_args
    assert call is not None
    return call[0][0]


def _last_kb(msg: AsyncMock):
    call = msg.edit_text.call_args
    assert call is not None
    return call[1].get("reply_markup")


# ---------------------------------------------------------------------------
# Callback encoding / decoding round-trips
# ---------------------------------------------------------------------------


def test_encode_menu_event_roundtrip() -> None:
    event_id = uuid4()
    data = encode_menu_event(event_id)
    assert data == f"m:event:{event_id}"
    parsed = parse_menu_callback(data)
    assert parsed is not None
    assert parsed.category == "event"
    assert parsed.event_id == event_id
    assert parsed.action is None


def test_encode_menu_event_action_roundtrip() -> None:
    event_id = uuid4()
    data = encode_menu_event_action(event_id, "pause")
    assert data == f"m:event:{event_id}:pause"
    parsed = parse_menu_callback(data)
    assert parsed is not None
    assert parsed.category == "event"
    assert parsed.event_id == event_id
    assert parsed.action == "pause"


def test_encode_menu_event_action_under_64_bytes() -> None:
    event_id = uuid4()
    for action in ("pause", "resume", "terminate", "terminate_confirm", "delete_confirm", "edit_duration", "dur_custom"):
        data = encode_menu_event_action(event_id, action)
        assert len(data.encode("utf-8")) <= 64


def test_parse_create_mode_callbacks() -> None:
    parsed = parse_menu_callback("m:event")
    assert parsed is not None
    assert parsed.category == "event"
    assert parsed.action is None
    assert parsed.event_id is None

    parsed = parse_menu_callback("m:event:create")
    assert parsed is not None
    assert parsed.category == "event"
    assert parsed.action == "create"
    assert parsed.event_id is None

    parsed = parse_menu_callback("m:event:dur_2d")
    assert parsed is not None
    assert parsed.category == "event"
    assert parsed.action == "dur_2d"
    assert parsed.event_id is None


def test_parse_event_callback_rejects_bad_uuid_as_create_action() -> None:
    parsed = parse_menu_callback("m:event:not-a-uuid:foo")
    assert parsed is not None
    assert parsed.category == "event"
    assert parsed.action == "not-a-uuid"
    assert parsed.extra == "foo"
    assert parsed.event_id is None


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------


def test_menu_root_has_eventos_temporales_button() -> None:
    from diana.telegram.keyboards import menu_root_keyboard

    kb = menu_root_keyboard()
    labels = [b.text for row in kb.inline_keyboard for b in row]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "📅 Eventos temporales" in labels
    assert "m:event" in callbacks


def test_menu_event_list_keyboard_shape() -> None:
    ev = _event()
    kb = menu_event_list_keyboard([ev])
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert encode_menu_event(ev.id) in callbacks
    assert "➕ Crear evento" in texts
    assert encode_menu("event", "create") in callbacks
    assert encode_menu("root") in callbacks


def test_menu_event_list_keyboard_truncates_long_body() -> None:
    ev = _event(body="X" * 80)
    kb = menu_event_list_keyboard([ev])
    btn = kb.inline_keyboard[0][0]
    assert btn.text == f"📅 {'X' * 30}"


def test_menu_event_detail_keyboard_toggle_by_pause_state() -> None:
    kb = menu_event_detail_keyboard(_event())
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "⏸️ Pausar" in texts

    kb_paused = menu_event_detail_keyboard(_event(is_paused=True))
    texts_paused = [b.text for row in kb_paused.inline_keyboard for b in row]
    assert "▶️ Reanudar" in texts_paused


def test_menu_event_duration_keyboard_create_vs_edit() -> None:
    create_kb = menu_event_duration_keyboard()
    create_datas = [b.callback_data for row in create_kb.inline_keyboard for b in row]
    assert "m:event:dur_today" in create_datas
    assert "m:event:dur_2d" in create_datas
    assert "m:event:create_cancel" in create_datas

    event_id = uuid4()
    edit_kb = menu_event_duration_keyboard(event_id)
    edit_datas = [b.callback_data for row in edit_kb.inline_keyboard for b in row]
    assert encode_menu_event_action(event_id, "dur_2d") in edit_datas
    assert encode_menu_event(event_id) in edit_datas


# ---------------------------------------------------------------------------
# List / detail dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_event_list_empty() -> None:
    store = _FakeEphemeralEventStore()
    service = _service(store)
    msg = _msg()
    await _render_event_list(msg, service, _OWNER_ID)
    assert _last_text(msg) == MENU_EVENT_EMPTY_TEXT
    kb = _last_kb(msg)
    assert encode_menu("event", "create") in [b.callback_data for row in kb.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_render_event_list_populated() -> None:
    ev = _event()
    service = _service(_FakeEphemeralEventStore([ev]))
    msg = _msg()
    await _render_event_list(msg, service, _OWNER_ID)
    assert _last_text(msg) == MENU_EVENT_LIST_TEXT
    kb = _last_kb(msg)
    assert encode_menu_event(ev.id) in [b.callback_data for row in kb.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_router_m_event_renders_list_and_answers() -> None:
    """The router-level m:event category routes to the list and acks the callback."""
    service = _service(_FakeEphemeralEventStore([_event()]))
    router = build_menu_router(
        owner_telegram_id=_OWNER_ID,
        vips=InMemoryVipStore(),
        ephemeral_event_service=service,
    )
    handler = router.callback_query.handlers[0].callback

    cb = AsyncMock(spec=CallbackQuery)
    cb.from_user = AsyncMock()
    cb.from_user.id = _OWNER_ID
    cb.data = "m:event"
    cb.message = _msg()
    cb.answer = AsyncMock()
    await handler(cb)

    cb.answer.assert_awaited_once()
    text = cb.message.edit_text.call_args[0][0]
    assert text == MENU_EVENT_LIST_TEXT


@pytest.mark.asyncio
async def test_detail_dispatch() -> None:
    ev = _event()
    service = _service(_FakeEphemeralEventStore([ev]))
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch(msg, event_id=ev.id, service=service, sessions=sessions)
    text = _last_text(msg)
    assert ev.body in text
    assert "Activo" in text
    kb = _last_kb(msg)
    assert encode_menu_event_action(ev.id, "pause") in [b.callback_data for row in kb.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_detail_missing_event_shows_error() -> None:
    service = _service(_FakeEphemeralEventStore())
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch(msg, event_id=uuid4(), service=service, sessions=sessions)
    assert "ya no existe" in _last_text(msg)


# ---------------------------------------------------------------------------
# Pause / resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_toggle() -> None:
    ev = _event()
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch(msg, action="pause", event_id=ev.id, service=service, sessions=sessions)
    updated = await store.get(ev.id)
    assert updated is not None and updated.is_paused is True
    kb_texts = [b.text for row in _last_kb(msg).inline_keyboard for b in row]
    assert "▶️ Reanudar" in kb_texts


@pytest.mark.asyncio
async def test_resume_toggle() -> None:
    ev = _event(is_paused=True)
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch(msg, action="resume", event_id=ev.id, service=service, sessions=sessions)
    updated = await store.get(ev.id)
    assert updated is not None and updated.is_paused is False
    kb_texts = [b.text for row in _last_kb(msg).inline_keyboard for b in row]
    assert "⏸️ Pausar" in kb_texts


# ---------------------------------------------------------------------------
# Terminate + delete confirmations (A7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_confirmed_ends_event() -> None:
    ev = _event()
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()
    sessions.record_confirmation(_OWNER_ID)

    msg = _msg()
    await _dispatch(msg, action="terminate_confirm", event_id=ev.id, service=service, sessions=sessions)
    updated = await store.get(ev.id)
    assert updated is not None and updated.end_at == _NOW
    assert _last_text(msg) == MENU_EVENT_EMPTY_TEXT  # re-rendered list


@pytest.mark.asyncio
async def test_delete_confirm_removes_event() -> None:
    ev = _event()
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()
    sessions.record_confirmation(_OWNER_ID)

    msg = _msg()
    await _dispatch(msg, action="delete_confirm", event_id=ev.id, service=service, sessions=sessions)
    assert await store.get(ev.id) is None
    assert _last_text(msg) == MENU_EVENT_EMPTY_TEXT


@pytest.mark.asyncio
async def test_delete_confirm_expired_returns_sentinel() -> None:
    """A7: a stale delete-confirm button must not delete the event."""
    ev = _event()
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()

    msg = _msg()
    result = await _dispatch(
        msg, action="delete_confirm", event_id=ev.id, service=service, sessions=sessions
    )
    assert result == "confirm_expired"
    assert await store.get(ev.id) is not None
    assert "expiró" in _last_text(msg)


@pytest.mark.asyncio
async def test_delete_shows_confirm_keyboard() -> None:
    ev = _event()
    service = _service(_FakeEphemeralEventStore([ev]))
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch(msg, action="delete", event_id=ev.id, service=service, sessions=sessions)
    kb = _last_kb(msg)
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert encode_menu_event_action(ev.id, "delete_confirm") in datas
    assert encode_menu_event(ev.id) in datas


# ---------------------------------------------------------------------------
# Modify sub-menu
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_modify_shows_submenu() -> None:
    ev = _event()
    service = _service(_FakeEphemeralEventStore([ev]))
    sessions = MenuSessionStore()
    msg = _msg()
    await _dispatch(msg, action="modify", event_id=ev.id, service=service, sessions=sessions)
    kb = _last_kb(msg)
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert encode_menu_event_action(ev.id, "edit_text") in datas
    assert encode_menu_event_action(ev.id, "edit_duration") in datas


# ---------------------------------------------------------------------------
# Creation wizard — text steps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_body_text_advances_to_duration() -> None:
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "event_body", last_bot_message_id=1, last_chat_id=42)
    session = sessions.pop(_OWNER_ID)
    assert session is not None
    service = _service(_FakeEphemeralEventStore())

    await _handle_event_body_text(_text_msg("promo 2x1"), _bot(), session, service, sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None
    assert retry.kind == "event_duration"
    assert retry.event_body == "promo 2x1"


@pytest.mark.asyncio
async def test_event_body_empty_keeps_wizard_alive() -> None:
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "event_body", last_bot_message_id=1, last_chat_id=42)
    session = sessions.pop(_OWNER_ID)
    assert session is not None
    service = _service(_FakeEphemeralEventStore())

    await _handle_event_body_text(_text_msg("   "), _bot(), session, service, sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None and retry.kind == "event_body"


@pytest.mark.asyncio
async def test_custom_start_absolute_date_advances_to_end() -> None:
    sessions = MenuSessionStore()
    sessions.start(
        _OWNER_ID, "event_custom_start", event_body="promo",
        last_bot_message_id=1, last_chat_id=42,
    )
    session = sessions.pop(_OWNER_ID)
    assert session is not None
    service = _service(_FakeEphemeralEventStore())

    await _handle_event_custom_start_text(_text_msg("2026-08-20"), _bot(), session, service, sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None
    assert retry.kind == "event_custom_end"
    assert retry.event_start_at is not None
    assert retry.event_start_at.date() == datetime(2026, 8, 20).date()


@pytest.mark.asyncio
async def test_custom_start_invalid_keeps_wizard_alive() -> None:
    sessions = MenuSessionStore()
    sessions.start(
        _OWNER_ID, "event_custom_start", event_body="promo",
        last_bot_message_id=1, last_chat_id=42,
    )
    session = sessions.pop(_OWNER_ID)
    assert session is not None
    service = _service(_FakeEphemeralEventStore())
    bot = _bot()

    await _handle_event_custom_start_text(_text_msg("no es fecha"), bot, session, service, sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None and retry.kind == "event_custom_start"
    bot.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_custom_end_relative_to_start_shows_confirm() -> None:
    sessions = MenuSessionStore()
    sessions.start(
        _OWNER_ID, "event_custom_end", event_body="promo", event_start_at=_NOW,
        last_bot_message_id=1, last_chat_id=42,
    )
    session = sessions.pop(_OWNER_ID)
    assert session is not None
    service = _service(_FakeEphemeralEventStore())
    bot = _bot()

    await _handle_event_custom_end_text(_text_msg("2 días"), bot, session, service, sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None
    assert retry.kind == "event_duration"
    assert retry.event_end_at is not None
    assert retry.event_end_at == _NOW + timedelta(days=2)
    kb = bot.edit_message_text.call_args.kwargs.get("reply_markup")
    assert kb is not None


@pytest.mark.asyncio
async def test_custom_end_invalid_keeps_wizard_alive() -> None:
    sessions = MenuSessionStore()
    sessions.start(
        _OWNER_ID, "event_custom_end", event_body="promo", event_start_at=_NOW,
        last_bot_message_id=1, last_chat_id=42,
    )
    session = sessions.pop(_OWNER_ID)
    assert session is not None
    service = _service(_FakeEphemeralEventStore())
    bot = _bot()

    await _handle_event_custom_end_text(_text_msg("mal"), bot, session, service, sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None and retry.kind == "event_custom_end"
    bot.edit_message_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# Creation wizard — callback steps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duration_button_create_mode_shows_confirm() -> None:
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "event_duration", event_body="promo", last_bot_message_id=1, last_chat_id=42)
    store = _FakeEphemeralEventStore()
    service = _service(store)
    msg = _msg()

    await _dispatch(msg, action="dur_2d", service=service, sessions=sessions)

    assert store._events == []  # not created until confirm
    text = _last_text(msg)
    assert "Confirma el evento" in text
    assert "promo" in text
    kb = _last_kb(msg)
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "m:event:create_confirm" in datas
    # the wizard window is kept in the session for the confirm step
    held = sessions.get(_OWNER_ID)
    assert held is not None and held.event_start_at is not None and held.event_end_at is not None


@pytest.mark.asyncio
async def test_create_confirm_persists_event() -> None:
    sessions = MenuSessionStore()
    sessions.start(
        _OWNER_ID, "event_duration", event_body="promo 2x1",
        event_start_at=_NOW, event_end_at=_NOW + timedelta(days=2),
    )
    store = _FakeEphemeralEventStore()
    service = _service(store)
    msg = _msg()

    await _dispatch(msg, action="create_confirm", service=service, sessions=sessions)

    assert len(store._events) == 1
    created = store._events[0]
    assert created.body == "promo 2x1"
    assert created.created_by == _OWNER_ID
    assert sessions.get(_OWNER_ID) is None  # session consumed


@pytest.mark.asyncio
async def test_create_cancel_clears_wizard() -> None:
    sessions = MenuSessionStore()
    sessions.start(_OWNER_ID, "event_duration", event_body="promo")
    store = _FakeEphemeralEventStore()
    service = _service(store)
    msg = _msg()

    await _dispatch(msg, action="create_cancel", service=service, sessions=sessions)

    assert store._events == []
    assert sessions.get(_OWNER_ID) is None
    assert _last_text(msg) == MENU_EVENT_EMPTY_TEXT


# ---------------------------------------------------------------------------
# Edit flow (recreate with the current backend — no service.update)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_body_updates_in_place() -> None:
    ev = _event(is_paused=True)
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()
    sessions.start(
        _OWNER_ID, "event_edit_body", event_id=ev.id,
        last_bot_message_id=1, last_chat_id=42,
    )
    session = sessions.pop(_OWNER_ID)
    assert session is not None
    bot = _bot()

    await _handle_event_edit_body_text(_text_msg("nuevo texto"), bot, session, service, sessions)

    assert await store.get(ev.id) is not None  # same id, updated in place
    assert len(store._events) == 1
    updated = await store.get(ev.id)
    assert updated.body == "nuevo texto"
    assert updated.is_paused is True  # pause state preserved
    assert sessions.get(_OWNER_ID) is None
    bot.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_body_empty_keeps_wizard_alive() -> None:
    ev = _event()
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()
    sessions.start(
        _OWNER_ID, "event_edit_body", event_id=ev.id,
        last_bot_message_id=1, last_chat_id=42,
    )
    session = sessions.pop(_OWNER_ID)
    assert session is not None

    await _handle_event_edit_body_text(_text_msg("  "), _bot(), session, service, sessions)

    retry = sessions.get(_OWNER_ID)
    assert retry is not None and retry.kind == "event_edit_body"
    assert len(store._events) == 1


@pytest.mark.asyncio
async def test_edit_duration_button_updates_in_place() -> None:
    ev = _event()
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()
    msg = _msg()

    await _dispatch(msg, action="dur_2d", event_id=ev.id, service=service, sessions=sessions)

    assert await store.get(ev.id) is not None  # same id, updated in place
    assert len(store._events) == 1
    updated = await store.get(ev.id)
    assert updated.body == ev.body
    # The handler computes the window from the real clock, so check the delta.
    delta = updated.end_at - datetime.now(UTC)
    assert timedelta(days=1, hours=23) < delta < timedelta(days=2, hours=1)
    assert updated.body in _last_text(msg)


@pytest.mark.asyncio
async def test_edit_custom_end_updates_in_place() -> None:
    ev = _event()
    store = _FakeEphemeralEventStore([ev])
    service = _service(store)
    sessions = MenuSessionStore()
    sessions.start(
        _OWNER_ID, "event_custom_end", event_start_at=_NOW, event_id=ev.id,
        last_bot_message_id=1, last_chat_id=42,
    )
    session = sessions.pop(_OWNER_ID)
    assert session is not None
    bot = _bot()

    await _handle_event_custom_end_text(_text_msg("2026-08-20"), bot, session, service, sessions)

    assert await store.get(ev.id) is not None  # same id, updated in place
    assert len(store._events) == 1
    updated = await store.get(ev.id)
    assert updated.end_at.year == 2026
    assert updated.end_at.month == 8
    assert updated.end_at.day == 20
    assert updated.start_at == _NOW
