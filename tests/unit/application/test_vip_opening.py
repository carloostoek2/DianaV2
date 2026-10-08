"""Arranque de conversación de un VIP nuevo.

Los mensajes que el VIP escribió antes de estar en la lista quedaron sin
responder. El arranque los junta y arma el turno, que termina siempre en la cola
de aprobación de la dueña.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.ports import BusinessConnectionRecord, VipRecord
from diana.application.vip_opening import VipOpeningService

_CHAT = 1280444712


def _rows(*roles_texts: tuple[str, str]) -> list[dict]:
    """Historial del más nuevo al más viejo, como lo devuelve get_recent."""
    return [
        {"role": role, "text": text, "telegram_message_id": 100 - i, "timestamp": None}
        for i, (role, text) in enumerate(roles_texts)
    ]


class _Runner:
    def __init__(self) -> None:
        self.calls = 0
        self.inbound = None
        self.turn_id = uuid4()

    async def handle_vip_message(self, incoming):
        self.calls += 1
        self.inbound = incoming
        return self.turn_id


class _History:
    def __init__(self, rows: list[dict] | Exception) -> None:
        self._rows = rows

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]:
        if isinstance(self._rows, Exception):
            raise self._rows
        return list(self._rows)


class _Vips:
    def __init__(self, record: VipRecord | None) -> None:
        self._record = record

    async def get_record_and_allowed(self, telegram_user_id: int):
        return self._record


class _Connections:
    def __init__(self, record: BusinessConnectionRecord | None) -> None:
        self._record = record

    async def get_active(self):
        return self._record


class _Coordinator:
    def __init__(self, live: list[object] | None = None) -> None:
        self._live = live or []

    async def list_non_terminal(self, chat_id: int) -> list[object]:
        return list(self._live)


def _vip(*, auto_send: bool = False) -> VipRecord:
    return VipRecord(
        id=uuid4(), telegram_user_id=_CHAT, display_name="Nuevo", auto_send=auto_send
    )


def _connection() -> BusinessConnectionRecord:
    return BusinessConnectionRecord(
        business_connection_id="bc-1",
        user_id=999,
        user_chat_id=_CHAT,
        date=datetime(2026, 10, 8, tzinfo=UTC),
        can_reply=True,
        is_enabled=True,
    )


_UNSET = object()


def _service(
    *,
    rows=None,
    vip=_UNSET,
    connection=_UNSET,
    live=None,
    max_messages: int = 3,
):
    runner = _Runner()
    service = VipOpeningService(
        runner=runner,
        history=_History(rows if rows is not None else _rows(("vip", "hola"))),
        vips=_Vips(_vip() if vip is _UNSET else vip),
        connections=_Connections(
            _connection() if connection is _UNSET else connection
        ),
        coordinator=_Coordinator(live),
        max_messages=max_messages,
    )
    return service, runner


@pytest.mark.asyncio
async def test_starts_a_turn_from_the_unanswered_messages() -> None:
    service, runner = _service(
        rows=_rows(("vip", "te mandé un video"), ("vip", "te gustó?"))
    )
    outcome = await service.start(_CHAT)
    assert outcome.kind == "started"
    assert outcome.messages == 2
    assert runner.calls == 1
    inbound = runner.inbound
    assert inbound.chat_id == _CHAT
    assert inbound.business_connection_id == "bc-1"
    assert inbound.channel_type == "vip"
    assert inbound.skip_coalesce is True
    assert "te mandé un video" in inbound.text
    assert "te gustó?" in inbound.text
    # El identificador del turno es el del último mensaje del VIP.
    # El turno se ancla al mensaje más reciente del VIP.
    assert inbound.telegram_message_id == 100


@pytest.mark.asyncio
async def test_only_the_last_messages_are_answered() -> None:
    service, runner = _service(
        rows=_rows(
            ("vip", "cinco"),
            ("vip", "cuatro"),
            ("vip", "tres"),
            ("vip", "dos"),
            ("vip", "uno"),
        ),
        max_messages=3,
    )
    outcome = await service.start(_CHAT)
    assert outcome.kind == "started"
    assert outcome.messages == 3
    assert "tres" in runner.inbound.text
    assert "cuatro" in runner.inbound.text
    assert "cinco" in runner.inbound.text
    assert "uno" not in runner.inbound.text


@pytest.mark.asyncio
async def test_nothing_to_answer_when_the_owner_wrote_last() -> None:
    service, runner = _service(
        rows=_rows(("owner", "ya te contesté"), ("vip", "hola"))
    )
    outcome = await service.start(_CHAT)
    assert outcome.kind == "skipped"
    assert outcome.reason == "nothing_to_answer"
    assert runner.calls == 0


@pytest.mark.asyncio
async def test_busy_chat_is_left_alone() -> None:
    service, runner = _service(live=[object()])
    outcome = await service.start(_CHAT)
    assert outcome.reason == "chat_busy"
    assert runner.calls == 0


@pytest.mark.asyncio
async def test_unknown_vip_is_skipped() -> None:
    service, runner = _service(vip=None)
    outcome = await service.start(_CHAT)
    assert outcome.reason == "vip_unknown"
    assert runner.calls == 0


@pytest.mark.asyncio
async def test_auto_send_vip_is_left_out() -> None:
    """El arranque siempre termina en aprobación: con envío automático no arranca."""
    service, runner = _service(vip=_vip(auto_send=True))
    outcome = await service.start(_CHAT)
    assert outcome.reason == "auto_send_enabled"
    assert runner.calls == 0


@pytest.mark.asyncio
async def test_without_a_live_connection_it_does_not_start() -> None:
    service, runner = _service(connection=None)
    outcome = await service.start(_CHAT)
    assert outcome.reason == "no_business_connection"
    assert runner.calls == 0


@pytest.mark.asyncio
async def test_history_read_failure_does_not_raise() -> None:
    service, runner = _service(rows=RuntimeError("db caída"))
    outcome = await service.start(_CHAT)
    assert outcome.reason == "nothing_to_answer"
    assert runner.calls == 0


@pytest.mark.asyncio
async def test_blank_trailing_messages_are_ignored() -> None:
    service, runner = _service(
        rows=_rows(("vip", "   "), ("vip", "te gustó?"))
    )
    outcome = await service.start(_CHAT)
    assert outcome.kind == "started"
    assert outcome.messages == 1
    assert runner.inbound.text.strip() == "te gustó?"


@pytest.mark.asyncio
async def test_seed_notifies_that_a_draft_is_waiting() -> None:
    """El aviso del alta cuenta que además quedó un borrador en la cola."""
    from diana.application.memory import (
        FakeOwnerNotifier,
        InMemoryMessageHistoryWriter,
    )
    from diana.application.vip_history_seed import (
        HistoryLine,
        VipHistorySeedService,
    )

    notifier = FakeOwnerNotifier()
    history = InMemoryMessageHistoryWriter()

    class _Fetcher:
        async def fetch_recent(self, user_id, *, limit, username=None):
            return [
                HistoryLine(role="vip", text="te mandé un video", telegram_message_id=1)
            ]

    service = VipHistorySeedService(
        history=history,
        fetcher=_Fetcher(),
        limit=20,
        notifier=notifier,
        opening=_OpeningStub(),
    )
    await service._seed_safe(_CHAT, username=None)
    assert any("cola de aprobación" in text for text, _ in notifier.infos)


class _OpeningStub:
    async def start(self, telegram_user_id: int):
        from diana.application.vip_opening import OpeningOutcome

        return OpeningOutcome(kind="started", turn_id=uuid4(), messages=1)
