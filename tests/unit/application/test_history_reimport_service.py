"""HistoryReimportService unit tests — fakes only (rotation + enqueue gating)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from diana.application.history_reimport import HistoryReimportService
from diana.application.memory_backfill_queue import EnqueueReport
from diana.application.vip_history_seed import SeedOutcome


@dataclass
class FakeVip:
    telegram_user_id: int


class FakeVips:
    def __init__(self, uids: list[int]) -> None:
        self._uids = list(uids)

    async def list_active(self) -> list[FakeVip]:
        return [FakeVip(uid) for uid in self._uids]


class FakeSeed:
    """Scripted seed: per-uid outcome or exception."""

    def __init__(
        self,
        outcomes: dict[int, SeedOutcome] | None = None,
        raise_on: set[int] | None = None,
    ) -> None:
        self._outcomes = outcomes or {}
        self._raise_on = raise_on or set()
        self.calls: list[int] = []

    async def seed_for_new_vip(
        self,
        telegram_user_id: int,
        *,
        username: str | None = None,
    ) -> SeedOutcome:
        self.calls.append(telegram_user_id)
        if telegram_user_id in self._raise_on:
            raise RuntimeError(f"telethon boom {telegram_user_id}")
        return self._outcomes.get(telegram_user_id, SeedOutcome(kind="ok", count=0))


class FakeBackfill:
    def __init__(self, status: str = "enqueued") -> None:
        self._status = status
        self.calls: list[int] = []

    async def enqueue_by_telegram_user(
        self, telegram_user_id: int, *, notify: bool = True
    ) -> EnqueueReport:
        self.calls.append(telegram_user_id)
        return EnqueueReport(status=self._status, telegram_user_id=telegram_user_id)


class FakeCursor:
    def __init__(self, cursor: int | None = None) -> None:
        self.cursor = cursor
        self.set_calls: list[int] = []

    async def get_cursor(self) -> int | None:
        return self.cursor

    async def set_cursor(self, telegram_user_id: int) -> None:
        self.cursor = telegram_user_id
        self.set_calls.append(telegram_user_id)


class FakeNotifier:
    def __init__(self) -> None:
        self.infos: list[str] = []

    async def notify_info(self, text: str) -> None:
        self.infos.append(text)


def _make(
    uids: list[int],
    *,
    cursor: int | None = None,
    outcomes: dict[int, SeedOutcome] | None = None,
    raise_on: set[int] | None = None,
    backfill_status: str = "enqueued",
    notifier: FakeNotifier | None = None,
) -> tuple[HistoryReimportService, FakeSeed, FakeBackfill, FakeCursor]:
    seed = FakeSeed(outcomes=outcomes, raise_on=raise_on)
    backfill = FakeBackfill(status=backfill_status)
    cur = FakeCursor(cursor=cursor)
    svc = HistoryReimportService(
        vips=FakeVips(uids),
        seed=seed,
        backfill=backfill,
        cursor=cur,
        notifier=notifier,
    )
    return svc, seed, backfill, cur


@pytest.mark.asyncio
async def test_first_cycle_picks_first_vip_and_advances_cursor() -> None:
    svc, seed, backfill, cur = _make([11, 22, 33])
    report = await svc.process_next()
    assert report.status == "processed"
    assert report.telegram_user_id == 11
    assert report.index == 1 and report.total == 3
    assert seed.calls == [11]
    assert cur.set_calls == [11]


@pytest.mark.asyncio
async def test_rotation_continues_after_cursor() -> None:
    svc, seed, backfill, cur = _make([11, 22, 33], cursor=11)
    report = await svc.process_next()
    assert report.telegram_user_id == 22
    assert report.index == 2
    assert cur.set_calls == [22]


@pytest.mark.asyncio
async def test_rotation_wraps_to_first_after_last() -> None:
    svc, seed, backfill, cur = _make([11, 22, 33], cursor=33)
    report = await svc.process_next()
    assert report.telegram_user_id == 11
    assert report.index == 1
    assert cur.set_calls == [11]


@pytest.mark.asyncio
async def test_enqueues_backfill_only_when_import_added_messages() -> None:
    svc, seed, backfill, cur = _make(
        [11, 22],
        outcomes={11: SeedOutcome(kind="ok", count=3, telegram_user_id=11)},
    )
    first = await svc.process_next()  # VIP 11: 3 imported → enqueue
    assert first.imported == 3
    assert backfill.calls == [11]
    second = await svc.process_next()  # VIP 22: 0 imported → no enqueue
    assert second.imported == 0
    assert backfill.calls == [11]


@pytest.mark.asyncio
async def test_seed_failure_reports_error_and_advances_cursor() -> None:
    notifier = FakeNotifier()
    svc, seed, backfill, cur = _make(
        [11, 22],
        raise_on={11},
        notifier=notifier,
    )
    report = await svc.process_next()
    assert report.status == "processed"
    assert report.telegram_user_id == 11
    assert report.error is not None
    assert backfill.calls == []
    assert cur.set_calls == [11]  # retried on the next rotation
    assert len(notifier.infos) == 1
    assert "falló" in notifier.infos[0]


@pytest.mark.asyncio
async def test_no_active_vips_is_idle() -> None:
    svc, seed, backfill, cur = _make([])
    report = await svc.process_next()
    assert report.status == "no_vip"
    assert seed.calls == []
    assert cur.set_calls == []


@pytest.mark.asyncio
async def test_owner_notified_only_for_imported_or_failed() -> None:
    notifier = FakeNotifier()
    svc, seed, backfill, cur = _make(
        [11, 22],
        outcomes={22: SeedOutcome(kind="ok", count=2, telegram_user_id=22)},
        notifier=notifier,
    )
    await svc.process_next()  # VIP 11: count=0 → silent
    assert notifier.infos == []
    await svc.process_next()  # VIP 22: count=2 → DM with step info
    assert len(notifier.infos) == 1
    assert "22" in notifier.infos[0]
    assert "paso 2/2" in notifier.infos[0]
    assert "2 mensajes nuevos importados" in notifier.infos[0]


@pytest.mark.asyncio
async def test_imported_with_backfill_already_pending_message() -> None:
    notifier = FakeNotifier()
    svc, seed, backfill, cur = _make(
        [11],
        outcomes={11: SeedOutcome(kind="ok", count=1, telegram_user_id=11)},
        backfill_status="already_pending",
        notifier=notifier,
    )
    report = await svc.process_next()
    assert report.backfill == "already_pending"
    assert "ya estaba en cola" in notifier.infos[0]
    assert "1 mensaje nuevo importado" in notifier.infos[0]
