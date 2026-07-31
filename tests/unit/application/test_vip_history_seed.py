"""VIP history seed on allowlist add (Telethon backfill → message_history)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from diana.application.memory import FakeOwnerNotifier, InMemoryMessageHistoryWriter
from diana.application.vip_history_seed import (
    HistoryLine,
    SeedOutcome,
    VipHistorySeedService,
    map_raw_messages_to_lines,
)


class FakeFetcher:
    def __init__(self, lines: list[HistoryLine] | Exception) -> None:
        self._lines = lines
        self.calls: list[tuple[int, int]] = []

    async def fetch_recent(
        self,
        user_id: int,
        *,
        limit: int,
        username: str | None = None,
    ) -> list[HistoryLine]:
        self.calls.append((user_id, limit))
        if isinstance(self._lines, Exception):
            raise self._lines
        return list(self._lines)


def _line(
    role: str = "vip",
    text: str = "hola",
    mid: int | None = 1,
) -> HistoryLine:
    return HistoryLine(
        role=role,  # type: ignore[arg-type]
        text=text,
        telegram_message_id=mid,
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )


def test_map_raw_messages_to_lines_roles_and_skip_empty() -> None:
    raw = [
        {"text": "hola VIP", "is_diana": False, "id": 10, "date": "2026-01-01T10:00:00+00:00"},
        {"text": "hola de Diana", "is_diana": True, "id": 11, "date": "2026-01-01T10:01:00+00:00"},
        {"text": "   ", "is_diana": False, "id": 12, "date": None},
        {"text": "", "is_diana": False, "media_kind": "foto", "id": 13, "date": None},
    ]
    lines = map_raw_messages_to_lines(raw)
    assert len(lines) == 3
    assert lines[0].role == "vip" and lines[0].text == "hola VIP"
    assert lines[1].role == "owner" and "Diana" in lines[1].text
    assert lines[2].text == "[foto]"


def test_seed_outcome_owner_messages() -> None:
    ok = SeedOutcome(kind="ok", count=3, telegram_user_id=99)
    assert "correcta" in ok.owner_message()
    assert "3 mensajes" in ok.owner_message()
    one = SeedOutcome(kind="ok", count=1, telegram_user_id=99)
    assert "1 mensaje)" in one.owner_message() or "1 mensaje" in one.owner_message()
    fail = SeedOutcome(kind="failed", count=0, telegram_user_id=99)
    assert "no se pudo importar" in fail.owner_message()


@pytest.mark.asyncio
async def test_seed_writes_chronological_history_when_empty() -> None:
    history = InMemoryMessageHistoryWriter()
    fetcher = FakeFetcher(
        [
            _line("vip", "msg1", 1),
            _line("owner", "msg2", 2),
            _line("vip", "msg3", 3),
        ]
    )
    svc = VipHistorySeedService(history=history, fetcher=fetcher, limit=20)
    outcome = await svc.seed_for_new_vip(999001)
    assert outcome.kind == "ok"
    assert outcome.count == 3
    recent = await history.get_recent(999001, limit=20)
    assert [r["text"] for r in recent] == ["msg1", "msg2", "msg3"]
    assert recent[0]["role"] == "vip"
    assert recent[1]["role"] == "owner"
    assert fetcher.calls == [(999001, 20)]


@pytest.mark.asyncio
async def test_seed_skips_when_history_already_present() -> None:
    history = InMemoryMessageHistoryWriter()
    await history.append(42, role="vip", text="already", telegram_message_id=1)
    fetcher = FakeFetcher([_line("vip", "new", 2)])
    svc = VipHistorySeedService(history=history, fetcher=fetcher, limit=20)
    outcome = await svc.seed_for_new_vip(42)
    assert outcome.kind == "skipped_existing"
    assert outcome.count == 0
    assert fetcher.calls == []
    recent = await history.get_recent(42, limit=10)
    assert len(recent) == 1
    assert recent[0]["text"] == "already"


@pytest.mark.asyncio
async def test_seed_noop_when_fetcher_disabled() -> None:
    history = InMemoryMessageHistoryWriter()
    svc = VipHistorySeedService(history=history, fetcher=None, limit=20)
    outcome = await svc.seed_for_new_vip(1)
    assert outcome.kind == "disabled"
    assert await history.get_recent(1, limit=5) == []


@pytest.mark.asyncio
async def test_seed_propagates_fetch_errors_without_partial_write() -> None:
    history = InMemoryMessageHistoryWriter()
    fetcher = FakeFetcher(RuntimeError("telethon down"))
    svc = VipHistorySeedService(history=history, fetcher=fetcher, limit=10)
    with pytest.raises(RuntimeError, match="telethon down"):
        await svc.seed_for_new_vip(7)
    assert await history.get_recent(7, limit=5) == []


@pytest.mark.asyncio
async def test_seed_safe_notifies_owner_on_success() -> None:
    history = InMemoryMessageHistoryWriter()
    fetcher = FakeFetcher([_line("vip", "hola", 1), _line("owner", "hey", 2)])
    notifier = FakeOwnerNotifier()
    svc = VipHistorySeedService(
        history=history, fetcher=fetcher, limit=20, notifier=notifier
    )
    await svc._seed_safe(555, username=None)  # noqa: SLF001 — unit path
    assert len(notifier.infos) == 1
    text, _ = notifier.infos[0]
    assert "555" in text
    assert "correcta" in text
    assert "2 mensaje" in text


@pytest.mark.asyncio
async def test_seed_safe_notifies_owner_on_failure() -> None:
    history = InMemoryMessageHistoryWriter()
    fetcher = FakeFetcher(RuntimeError("telethon down"))
    notifier = FakeOwnerNotifier()
    svc = VipHistorySeedService(
        history=history, fetcher=fetcher, limit=20, notifier=notifier
    )
    await svc._seed_safe(777, username=None)  # noqa: SLF001
    assert len(notifier.infos) == 1
    text, _ = notifier.infos[0]
    assert "777" in text
    assert "no se pudo importar" in text
