"""FreezeCheckMiddleware — frozen VIP messages silently dropped."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, User

from diana.application.memory import InMemoryVipStore
from diana.application.ports import (
    DoctrineNotification,
    GrayZoneServicePort,
    VipRecord,
)
from diana.telegram.freeze_middleware import FreezeCheckMiddleware

# ---- Fake implementations for reminder tests ----


class _FakeGrayZoneView:
    """Minimal structural match for GrayZoneQueryView used in tests."""

    def __init__(
        self,
        *,
        turn_id,
        question="hola",
        draft="borrador",
        freeze_until=None,
        status: str = "open",
    ):
        self.id = uuid4()
        self.turn_id = turn_id
        self.question = question
        self.draft = draft
        self.freeze_until = freeze_until
        self.status = status


class _FakeGrayZone:
    """Structural match for GrayZoneServicePort."""

    def __init__(
        self,
        query: _FakeGrayZoneView | None = None,
        *,
        error: bool = False,
        chat_query: _FakeGrayZoneView | None = None,
    ):
        self._query = query
        self._chat_query = chat_query if chat_query is not None else query
        self._error = error

    async def get_open_query_by_vip_id(self, vip_id):
        if self._error:
            raise RuntimeError("db down")
        return self._query

    async def get_open_query_by_chat_id(self, chat_id):
        if self._error:
            raise RuntimeError("db down")
        return self._chat_query

    async def get_open_query_by_turn_id(self, turn_id):
        return None

    async def resolve_with_doctrine(self, *args, **kwargs):
        raise NotImplementedError

    async def confirm_and_apply(self, *args, **kwargs):
        raise NotImplementedError

    async def discard_and_close(self, *args, **kwargs):
        raise NotImplementedError

    async def expire_old_queries(self, *args, **kwargs):
        return []


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


@pytest.mark.asyncio
async def test_freeze_lookup_error_fail_closed() -> None:
    """VIP lookup exception must drop the update (fail-closed)."""
    vips = AsyncMock()
    vips.get_by_telegram_user_id = AsyncMock(side_effect=RuntimeError("db down"))
    mw = FreezeCheckMiddleware(vips=vips)
    handler = AsyncMock(return_value="next")
    data: dict = {}
    with patch("diana.telegram.freeze_middleware.logger") as mock_logger:
        result = await mw(handler, _biz_msg(555), data)
    assert result is None
    handler.assert_not_awaited()
    assert "_vip_record" not in data
    mock_logger.exception.assert_called()
    assert mock_logger.exception.call_args.args[0] == "freeze_check_lookup_error"
    extra = mock_logger.exception.call_args.kwargs.get("extra") or {}
    assert extra.get("telegram_user_id") == 555


@pytest.mark.asyncio
async def test_freeze_naive_frozen_until_still_drops() -> None:
    """Naive frozen_until must not TypeError; treat as UTC and drop when future."""
    naive_future = (datetime.now(UTC) + timedelta(hours=2)).replace(tzinfo=None)
    assert naive_future.tzinfo is None
    rec = VipRecord(
        id=uuid4(),
        telegram_user_id=666,
        display_name="Vip",
        is_active=True,
        frozen_until=naive_future,
    )
    vips = AsyncMock()
    vips.get_by_telegram_user_id = AsyncMock(return_value=rec)
    mw = FreezeCheckMiddleware(vips=vips)
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _biz_msg(666), {})
    assert result is None
    handler.assert_not_awaited()


# ---- Reminder notification tests ----


@pytest.mark.asyncio
async def test_frozen_vip_with_open_query_sends_reminder() -> None:
    """Frozen VIP + open gray zone query → notify owner, still drop message."""
    vips = InMemoryVipStore()
    rec = await vips.add(777, display_name="Vip")
    frozen_until = datetime.now(UTC) + timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    turn_id = uuid4()
    query = _FakeGrayZoneView(turn_id=turn_id)
    gray_zone = _FakeGrayZone(query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(vips=vips, gray_zone=gray_zone, notifier=notifier)
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _biz_msg(777), {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_awaited_once()
    payload: DoctrineNotification = notifier.notify_doctrine.call_args[0][0]
    assert payload.turn_id == turn_id
    assert payload.chat_id == 42
    assert payload.reason == "recordatorio_zona_gris"


@pytest.mark.asyncio
async def test_frozen_vip_reminder_debounce() -> None:
    """Second message within TTL must NOT send a second reminder."""
    vips = InMemoryVipStore()
    rec = await vips.add(888, display_name="Vip")
    frozen_until = datetime.now(UTC) + timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    query = _FakeGrayZoneView(turn_id=uuid4())
    gray_zone = _FakeGrayZone(query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(vips=vips, gray_zone=gray_zone, notifier=notifier, reminder_ttl_s=3600.0)
    handler = AsyncMock(return_value="next")

    await mw(handler, _biz_msg(888), {})
    assert notifier.notify_doctrine.await_count == 1

    await mw(handler, _biz_msg(888, text="otro"), {})
    assert notifier.notify_doctrine.await_count == 1  # still 1


@pytest.mark.asyncio
async def test_frozen_vip_no_open_query_drops_without_notify() -> None:
    """No open query → drop without notification."""
    vips = InMemoryVipStore()
    rec = await vips.add(999, display_name="Vip")
    frozen_until = datetime.now(UTC) + timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    gray_zone = _FakeGrayZone(query=None)  # no open query
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(vips=vips, gray_zone=gray_zone, notifier=notifier)
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _biz_msg(999), {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_frozen_vip_reminder_gray_zone_none_skips() -> None:
    """gray_zone=None → drop without notification (backward compat)."""
    vips = InMemoryVipStore()
    rec = await vips.add(1010, display_name="Vip")
    frozen_until = datetime.now(UTC) + timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    notifier = AsyncMock()
    mw = FreezeCheckMiddleware(vips=vips, gray_zone=None, notifier=notifier)
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _biz_msg(1010), {})

    assert result is None
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_frozen_vip_reminder_lookup_error_drops() -> None:
    """Gray zone lookup exception → drop without notify (fail-soft)."""
    vips = InMemoryVipStore()
    rec = await vips.add(1111, display_name="Vip")
    frozen_until = datetime.now(UTC) + timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    gray_zone = _FakeGrayZone(error=True)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(vips=vips, gray_zone=gray_zone, notifier=notifier)
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _biz_msg(1111), {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_frozen_vip_reminder_notifier_exception_drops() -> None:
    """Notifier exception → still drop the message (fail-soft)."""
    vips = InMemoryVipStore()
    rec = await vips.add(1212, display_name="Vip")
    frozen_until = datetime.now(UTC) + timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    query = _FakeGrayZoneView(turn_id=uuid4())
    gray_zone = _FakeGrayZone(query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(side_effect=RuntimeError("tg down"))

    mw = FreezeCheckMiddleware(vips=vips, gray_zone=gray_zone, notifier=notifier)
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _biz_msg(1212), {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_awaited_once()


@pytest.mark.asyncio
async def test_frozen_vip_edited_message_skips_reminder() -> None:
    """Edited message from frozen VIP → drop but no reminder."""
    vips = InMemoryVipStore()
    rec = await vips.add(1313, display_name="Vip")
    frozen_until = datetime.now(UTC) + timedelta(hours=1)
    await vips.freeze_vip(rec.id, frozen_until)

    query = _FakeGrayZoneView(turn_id=uuid4())
    gray_zone = _FakeGrayZone(query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(vips=vips, gray_zone=gray_zone, notifier=notifier)
    handler = AsyncMock(return_value="next")

    msg = Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=1313, is_bot=False, first_name="U"),
        text="hello",
        business_connection_id="bc-1",
        edit_date=12345,
    )
    result = await mw(handler, msg, {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_not_awaited()


# ---- Atencion chat freeze (A1, gated by general mode) ----


def _atencion_msg(user_id: int, text: str = "hola", chat_id: int = 42) -> Message:
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="U"),
        text=text,
        business_connection_id="bc-1",
    )


def _future_freeze() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


@pytest.mark.asyncio
async def test_atencion_frozen_chat_drops_with_general_mode() -> None:
    """A1: open atencion query with future freeze_until drops the message."""
    vips = InMemoryVipStore()  # user 1414 is NOT a VIP
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=_future_freeze())
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1414), {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_awaited_once()
    payload: DoctrineNotification = notifier.notify_doctrine.call_args[0][0]
    assert payload.turn_id == query.turn_id
    assert payload.chat_id == 42
    assert payload.reason == "recordatorio_zona_gris"


@pytest.mark.asyncio
async def test_atencion_awaiting_send_hold_still_freezes() -> None:
    """Doctrine awaiting_send (post rule+regen) still freezes Atención until send."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(
        turn_id=uuid4(),
        freeze_until=_future_freeze(),
        status="awaiting_send",
    )
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1415), {})

    assert result is None
    handler.assert_not_awaited()
    assert query.status == "awaiting_send"
    notifier.notify_doctrine.assert_awaited_once()


@pytest.mark.asyncio
async def test_atencion_freeze_off_when_general_mode_disabled() -> None:
    """Flag OFF: atencion chat freeze must NOT engage (byte-identical)."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=_future_freeze())
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips, gray_zone=gray_zone, notifier=notifier, general_mode_enabled=False
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1415), {})

    assert result == "next"
    handler.assert_awaited_once()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_atencion_chat_expired_freeze_passes() -> None:
    """A1: expired freeze_until lets the message through."""
    vips = InMemoryVipStore()
    past = datetime.now(UTC) - timedelta(hours=1)
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=past)
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1416), {})

    assert result == "next"
    handler.assert_awaited_once()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_atencion_chat_no_open_query_passes() -> None:
    """A1: no open query → message passes through."""
    vips = InMemoryVipStore()
    gray_zone = _FakeGrayZone(chat_query=None)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1417), {})

    assert result == "next"
    handler.assert_awaited_once()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_atencion_chat_lookup_error_fails_open() -> None:
    """A1: gray zone lookup failure passes through (fail-soft), no drop."""
    vips = InMemoryVipStore()
    gray_zone = _FakeGrayZone(error=True)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    with patch("diana.telegram.freeze_middleware.logger") as mock_logger:
        result = await mw(handler, _atencion_msg(1418), {})

    assert result == "next"
    handler.assert_awaited_once()
    notifier.notify_doctrine.assert_not_awaited()
    assert mock_logger.exception.call_args.args[0] == "atencion_freeze_lookup_error"


@pytest.mark.asyncio
async def test_atencion_chat_reminder_debounce() -> None:
    """A1: second message within TTL does not send a second reminder."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=_future_freeze())
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
        reminder_ttl_s=3600.0,
    )
    handler = AsyncMock(return_value="next")

    await mw(handler, _atencion_msg(1419), {})
    assert notifier.notify_doctrine.await_count == 1

    await mw(handler, _atencion_msg(1419, text="otro"), {})
    assert notifier.notify_doctrine.await_count == 1  # still 1


@pytest.mark.asyncio
async def test_atencion_chat_notifier_exception_still_drops() -> None:
    """A1: notifier failure still drops the message (fail-soft)."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=_future_freeze())
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(side_effect=RuntimeError("tg down"))

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1420), {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_awaited_once()


@pytest.mark.asyncio
async def test_atencion_chat_edited_message_skips_reminder() -> None:
    """A1: edited atencion message drops but does not re-nag."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=_future_freeze())
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")

    msg = Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=1421, is_bot=False, first_name="U"),
        text="hello",
        business_connection_id="bc-1",
        edit_date=12345,
    )
    result = await mw(handler, msg, {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_atencion_chat_command_passes_through_freeze() -> None:
    """F11: a /-prefixed command (e.g. /start) is never dropped by the freeze."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=_future_freeze())
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1422, text="/start"), {})

    assert result == "next"
    handler.assert_awaited_once()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_atencion_chat_freeze_until_none_passes() -> None:
    """F13: open query without freeze_until never freezes the chat."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=None)
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1423), {})

    assert result == "next"
    handler.assert_awaited_once()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_atencion_chat_naive_future_freeze_drops() -> None:
    """F13: naive (tz-less) future freeze_until is normalized and enforced."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(
        turn_id=uuid4(),
        freeze_until=datetime.now(UTC) + timedelta(hours=1),
    )
    query.freeze_until = query.freeze_until.replace(tzinfo=None)  # naive
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1424), {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_awaited_once()


@pytest.mark.asyncio
async def test_atencion_chat_no_gray_zone_service_passes() -> None:
    """F13: gray_zone=None with general mode ON can never freeze (no-op)."""
    vips = InMemoryVipStore()
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=None,
        notifier=notifier,
        general_mode_enabled=True,
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1425), {})

    assert result == "next"
    handler.assert_awaited_once()
    notifier.notify_doctrine.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_reminder_dict_prunes_stale_entries() -> None:
    """F7: stale debounce timestamps are pruned so the dicts stay bounded."""
    vips = InMemoryVipStore()
    query = _FakeGrayZoneView(turn_id=uuid4(), freeze_until=_future_freeze())
    gray_zone = _FakeGrayZone(chat_query=query)
    notifier = AsyncMock()
    notifier.notify_doctrine = AsyncMock(return_value=42)

    mw = FreezeCheckMiddleware(
        vips=vips,
        gray_zone=gray_zone,
        notifier=notifier,
        general_mode_enabled=True,
        reminder_ttl_s=1200.0,
    )
    # Stale debounce timestamps (past TTL) for the current chat AND another.
    stale = datetime.now(UTC) - timedelta(hours=2)
    mw._last_chat_reminder[42] = stale  # noqa: SLF001
    mw._last_chat_reminder[999] = stale  # noqa: SLF001
    handler = AsyncMock(return_value="next")
    result = await mw(handler, _atencion_msg(1426), {})

    assert result is None
    handler.assert_not_awaited()
    notifier.notify_doctrine.assert_awaited_once()
    # The unrelated chat's stale entry was pruned; the current chat's is fresh.
    assert 999 not in mw._last_chat_reminder  # noqa: SLF001
    assert datetime.now(UTC) - mw._last_chat_reminder[42] < timedelta(minutes=1)  # noqa: SLF001
