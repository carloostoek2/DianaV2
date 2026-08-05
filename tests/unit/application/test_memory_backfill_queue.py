"""MemoryBackfillQueue unit tests — fakes only, no DB / no real sleeps."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import pytest

from diana.application.memory_backfill_queue import MemoryBackfillQueue
from diana.application.memory_backfill_service import (
    BackfillReport,
    HechoExtracted,
    WindowExtractionResult,
)
from diana.application.ports import BackfillJobRecord, VipRecord

FAKE_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

_SECTION = Literal["identidad", "preferencias", "comercial", "limites", "sensible"]


def _hecho(texto: str, seccion: _SECTION = "preferencias") -> HechoExtracted:
    return HechoExtracted(seccion=seccion, texto=texto)


def _vip(tg_id: int, *, name: str | None = None) -> VipRecord:
    return VipRecord(
        id=uuid4(), telegram_user_id=tg_id, display_name=name, is_active=True
    )


class FakeQueueStore:
    """In-memory BackfillQueueStore double (dict + FIFO by created_at)."""

    def __init__(self) -> None:
        self.jobs: dict[UUID, BackfillJobRecord] = {}
        self.enqueue_calls: list[tuple[UUID, int]] = []
        self.pop_calls = 0
        self.save_calls: list[tuple[UUID, int, dict, int]] = []
        self.done_calls: list[tuple[UUID, str]] = []
        self.failed_calls: list[tuple[UUID, str]] = []
        self.requeue_calls: list[tuple[UUID, int, str | None]] = []
        self.recover_calls = 0
        self.recover_max_ages: list[timedelta | None] = []
        self.since_calls: list[tuple[UUID, datetime]] = []
        self.since_failed_calls: list[tuple[UUID, datetime]] = []

    def _has_active(self, vip_id: UUID) -> bool:
        return any(
            j.vip_id == vip_id and j.status in ("pending", "processing")
            for j in self.jobs.values()
        )

    async def enqueue(self, vip_id: UUID, chat_id: int) -> BackfillJobRecord | None:
        self.enqueue_calls.append((vip_id, chat_id))
        if self._has_active(vip_id):
            return None
        job = BackfillJobRecord(
            id=uuid4(),
            vip_id=vip_id,
            chat_id=chat_id,
            status="pending",
            window_index=0,
            state={},
            attempts=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.jobs[job.id] = job
        return job

    async def pop_pending(self) -> BackfillJobRecord | None:
        self.pop_calls += 1
        pending = [j for j in self.jobs.values() if j.status == "pending"]
        if not pending:
            return None
        job = min(pending, key=lambda j: (j.created_at, j.id))
        job.status = "processing"
        job.updated_at = datetime.now(UTC)
        # Snapshot semantics like the real repo (_to_record): later store
        # mutations (e.g. save_progress) must not leak into this record.
        return job.model_copy(deep=True)

    async def save_progress(
        self, job_id: UUID, *, window_index: int, state: dict, attempts: int
    ) -> None:
        self.save_calls.append((job_id, window_index, state, attempts))
        job = self.jobs[job_id]
        job.status = "pending"
        job.window_index = window_index
        job.state = state
        job.attempts = attempts
        job.updated_at = datetime.now(UTC)

    async def mark_done(self, job_id: UUID, *, outcome: str) -> None:
        self.done_calls.append((job_id, outcome))
        job = self.jobs[job_id]
        job.status = "done"
        job.outcome = outcome
        job.updated_at = datetime.now(UTC)

    async def mark_failed(self, job_id: UUID, *, error: str) -> None:
        self.failed_calls.append((job_id, error))
        job = self.jobs[job_id]
        job.status = "failed"
        job.last_error = error
        job.updated_at = datetime.now(UTC)

    async def requeue(
        self, job_id: UUID, *, attempts: int, error: str | None = None
    ) -> None:
        self.requeue_calls.append((job_id, attempts, error))
        job = self.jobs[job_id]
        job.status = "pending"
        job.attempts = attempts
        job.last_error = error
        job.updated_at = datetime.now(UTC)

    async def recover_stale(self, *, max_age: timedelta | None = None) -> int:
        self.recover_calls += 1
        self.recover_max_ages.append(max_age)
        n = 0
        cutoff = datetime.now(UTC) - (max_age or timedelta(hours=1))
        for job in self.jobs.values():
            if job.status == "processing" and job.updated_at < cutoff:
                job.status = "pending"
                n += 1
        return n

    async def has_recent_empty_done(
        self, vip_id: UUID, *, since: datetime
    ) -> bool:
        self.since_calls.append((vip_id, since))
        return any(
            j.vip_id == vip_id
            and j.status == "done"
            and j.outcome == "empty_history"
            and j.updated_at >= since
            for j in self.jobs.values()
        )

    async def has_recent_failed(
        self, vip_id: UUID, *, since: datetime
    ) -> bool:
        self.since_failed_calls.append((vip_id, since))
        return any(
            j.vip_id == vip_id and j.status == "failed" and j.updated_at >= since
            for j in self.jobs.values()
        )


class FakeBackfill:
    """MemoryBackfillService double: scripted extract results + call records."""

    def __init__(
        self,
        results: list[WindowExtractionResult] | None = None,
        *,
        finalize_status: str = "ok",
    ) -> None:
        self.results: deque[WindowExtractionResult] = deque(results or [])
        self.extract_window_calls: list[tuple[UUID, int, int, list[HechoExtracted]]] = []
        self.finalize_calls: list[tuple[UUID, int, list[HechoExtracted], int]] = []
        self.raise_on_extract = False
        self.finalize_status = finalize_status

    async def extract_window(
        self,
        vip_id: UUID,
        chat_id: int,
        *,
        window_index: int,
        already: list[HechoExtracted] | None = None,
    ) -> WindowExtractionResult:
        self.extract_window_calls.append(
            (vip_id, chat_id, window_index, list(already or []))
        )
        if self.raise_on_extract:
            raise RuntimeError("fake backfill boom")
        if not self.results:
            raise RuntimeError("FakeBackfill result queue is empty")
        return self.results.popleft()

    async def finalize_profile(
        self,
        vip_id: UUID,
        chat_id: int,
        *,
        hechos: list[HechoExtracted],
        windows: int,
    ) -> BackfillReport:
        self.finalize_calls.append((vip_id, chat_id, list(hechos), windows))
        return BackfillReport(
            status=self.finalize_status,
            vip_id=vip_id,
            facts=len(hechos),
            windows=windows,
        )


class FakeVips:
    def __init__(self, records: list[VipRecord]) -> None:
        self._by_tg = {r.telegram_user_id: r for r in records}
        self._by_id = {r.id: r for r in records}

    async def get_by_telegram_user_id(
        self, telegram_user_id: int
    ) -> VipRecord | None:
        return self._by_tg.get(telegram_user_id)

    async def get_by_id(self, vip_id: UUID) -> VipRecord | None:
        return self._by_id.get(vip_id)

    async def list_active(self) -> list[VipRecord]:
        return [r for r in self._by_tg.values() if r.is_active]


class FakeHistory:
    def __init__(self, counts: dict[int, int]) -> None:
        self._counts = dict(counts)
        self.calls: list[tuple[int, int]] = []
        self.count_calls: list[int] = []

    async def list_all(self, chat_id: int, *, page_size: int = 500) -> list[dict]:
        self.calls.append((chat_id, page_size))
        return [{"text": "msg"} for _ in range(self._counts.get(chat_id, 0))]

    async def count(self, chat_id: int) -> int:
        self.count_calls.append(chat_id)
        return self._counts.get(chat_id, 0)


class FakeMemories:
    def __init__(self, profiles: set[UUID] | None = None) -> None:
        self._profiles = set(profiles or ())
        self.calls: list[UUID] = []

    async def has_profile(self, vip_id: UUID) -> bool:
        self.calls.append(vip_id)
        return vip_id in self._profiles


class FakeNotifier:
    def __init__(self) -> None:
        self.infos: list[str] = []

    async def notify_draft(self, payload: object) -> int | None:
        return None

    async def notify_escalation(self, payload: object) -> None:
        return None

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        self.infos.append(text)

    async def notify_doctrine(self, payload: object) -> int | None:
        return None


class FakeWake:
    def __init__(self) -> None:
        self.set_count = 0

    def set(self) -> None:
        self.set_count += 1


def _make_queue(
    *,
    enabled: bool = True,
    store: FakeQueueStore | None = None,
    backfill: FakeBackfill | None = None,
    vips: FakeVips | None = None,
    history: FakeHistory | None = None,
    memories: FakeMemories | None = None,
    notifier: FakeNotifier | None = None,
    window_size: int = 200,
    max_attempts: int = 3,
    wake: FakeWake | None = None,
    clock=None,
) -> MemoryBackfillQueue:
    return MemoryBackfillQueue(
        enabled=enabled,
        store=store or FakeQueueStore(),  # type: ignore[arg-type]
        backfill=backfill or FakeBackfill(),  # type: ignore[arg-type]
        vips=vips or FakeVips([]),  # type: ignore[arg-type]
        history=history or FakeHistory({}),  # type: ignore[arg-type]
        memories=memories or FakeMemories(),  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        window_size=window_size,
        max_attempts=max_attempts,
        wake=wake,  # type: ignore[arg-type]
        clock=clock or (lambda: FAKE_NOW),
    )


# ----------------------------------------------------------------------
# enqueue
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_disabled_noop() -> None:
    store = FakeQueueStore()
    queue = _make_queue(enabled=False, store=store)
    report = await queue.enqueue_by_telegram_user(123)
    assert report.status == "disabled"
    assert report.telegram_user_id == 123
    assert store.enqueue_calls == []


@pytest.mark.asyncio
async def test_enqueue_computes_steps_and_notifies() -> None:
    vip = _vip(123, name="Ana")
    store = FakeQueueStore()
    notifier = FakeNotifier()
    wake = FakeWake()
    queue = _make_queue(
        store=store,
        vips=FakeVips([vip]),
        history=FakeHistory({123: 450}),
        notifier=notifier,
        wake=wake,
    )

    report = await queue.enqueue_by_telegram_user(123)

    assert report.status == "enqueued"
    assert report.vip_id == vip.id
    assert report.name == "Ana"
    assert report.steps == 3  # ceil(450 / 200)
    assert store.enqueue_calls == [(vip.id, 123)]
    assert notifier.infos == ["Perfil de Ana en cola — se procesará en ~3 pasos"]
    assert wake.set_count == 1


@pytest.mark.asyncio
async def test_enqueue_duplicate_already_pending() -> None:
    vip = _vip(123, name="Ana")
    store = FakeQueueStore()
    notifier = FakeNotifier()
    # First enqueue inserts a job; the second hits the active-VIP idempotency.
    queue = _make_queue(
        store=store, vips=FakeVips([vip]), history=FakeHistory({123: 10}),
        notifier=notifier,
    )
    first = await queue.enqueue_by_telegram_user(123)
    assert first.status == "enqueued"

    second = await queue.enqueue_by_telegram_user(123)
    assert second.status == "already_pending"
    assert second.steps == 1
    assert notifier.infos == [
        "Perfil de Ana en cola — se procesará en ~1 pasos",
        "El perfil de Ana ya está en cola (se procesará pronto).",
    ]


@pytest.mark.asyncio
async def test_enqueue_unknown_vip_no_vip() -> None:
    store = FakeQueueStore()
    queue = _make_queue(store=store, vips=FakeVips([]))
    report = await queue.enqueue_by_telegram_user(999)
    assert report.status == "no_vip"
    assert store.enqueue_calls == []


@pytest.mark.asyncio
async def test_schedule_enqueue_fire_and_forget() -> None:
    vip = _vip(123, name="Ana")
    store = FakeQueueStore()
    notifier = FakeNotifier()
    queue = _make_queue(
        store=store,
        vips=FakeVips([vip]),
        history=FakeHistory({123: 5}),
        notifier=notifier,
    )

    queue.schedule_enqueue(123)
    # Let the background task run; then await it so the test never leaks tasks.
    for _ in range(20):
        if store.enqueue_calls:
            break
        await asyncio.sleep(0)
    tasks = [
        t for t in asyncio.all_tasks()
        if t.get_name().startswith("backfill-enqueue-")
    ]
    await asyncio.gather(*tasks)

    assert store.enqueue_calls == [(vip.id, 123)]
    assert notifier.infos == ["Perfil de Ana en cola — se procesará en ~1 pasos"]


# ----------------------------------------------------------------------
# process_one
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_one_idle_when_empty() -> None:
    queue = _make_queue()
    report = await queue.process_one()
    assert report.status == "idle"
    assert report.outcome is None


@pytest.mark.asyncio
async def test_process_one_window_then_requeue() -> None:
    vip = _vip(123)
    store = FakeQueueStore()
    hecho = _hecho("le gusta viajar")
    backfill = FakeBackfill(
        [WindowExtractionResult([hecho], total_windows=3)]
    )
    queue = _make_queue(store=store, backfill=backfill, vips=FakeVips([vip]))
    job = await store.enqueue(vip.id, 123)
    assert job is not None

    report = await queue.process_one()

    assert report.status == "processed"
    assert report.outcome == "window_done"
    assert report.window_index == 0
    assert backfill.finalize_calls == []
    assert len(store.save_calls) == 1
    job_id, window_index, state, attempts = store.save_calls[0]
    assert window_index == 1
    assert attempts == 0
    assert state["hechos"] == [hecho.model_dump()]
    job = store.jobs[job_id]
    assert job.status == "pending"
    assert job.window_index == 1


@pytest.mark.asyncio
async def test_process_one_finalizes_last_window() -> None:
    vip = _vip(123)
    store = FakeQueueStore()
    hecho = _hecho("le gusta el café")
    backfill = FakeBackfill(
        [WindowExtractionResult([hecho], total_windows=3)]
    )
    queue = _make_queue(store=store, backfill=backfill, vips=FakeVips([vip]))
    # Pre-seed a job at the last window (window_index=2 of 3).
    job = await store.enqueue(vip.id, 123)
    assert job is not None
    job.window_index = 2

    report = await queue.process_one()

    assert report.status == "processed"
    assert report.outcome == "ok"
    assert len(backfill.finalize_calls) == 1
    _, _, hechos, windows = backfill.finalize_calls[0]
    assert hechos == [hecho]
    assert windows == 3
    assert store.done_calls == [(job.id, "ok")]
    assert store.save_calls == []


@pytest.mark.asyncio
async def test_process_one_resumes_from_state() -> None:
    vip = _vip(123)
    store = FakeQueueStore()
    prev = _hecho("ya sabía esto")
    backfill = FakeBackfill(
        [WindowExtractionResult([_hecho("hecho nuevo")], total_windows=1)]
    )
    queue = _make_queue(store=store, backfill=backfill, vips=FakeVips([vip]))
    job = await store.enqueue(vip.id, 123)
    assert job is not None
    job.state = {"hechos": [prev.model_dump()]}
    job.window_index = 0

    report = await queue.process_one()

    assert report.outcome == "ok"
    # extract_window received the accumulated facts deserialized back.
    assert len(backfill.extract_window_calls) == 1
    _, _, window_index, already = backfill.extract_window_calls[0]
    assert window_index == 0
    assert already == [prev]
    # finalize got accumulated + new.
    _, _, hechos, _ = backfill.finalize_calls[0]
    assert hechos == [prev, _hecho("hecho nuevo")]


@pytest.mark.asyncio
async def test_process_one_empty_history_marks_done() -> None:
    vip = _vip(123)
    store = FakeQueueStore()
    backfill = FakeBackfill(
        [WindowExtractionResult([], 0, history_empty=True)]
    )
    queue = _make_queue(store=store, backfill=backfill, vips=FakeVips([vip]))
    job = await store.enqueue(vip.id, 123)
    assert job is not None

    report = await queue.process_one()

    assert report.status == "processed"
    assert report.outcome == "empty_history"
    assert store.done_calls == [(job.id, "empty_history")]
    assert backfill.finalize_calls == []


@pytest.mark.asyncio
async def test_process_one_window_failure_retries_then_fails() -> None:
    vip = _vip(123)
    store = FakeQueueStore()
    backfill = FakeBackfill(
        [WindowExtractionResult([], 0, failed=True)] * 3
    )
    queue = _make_queue(
        store=store, backfill=backfill, vips=FakeVips([vip]), max_attempts=3
    )
    job = await store.enqueue(vip.id, 123)
    assert job is not None

    r1 = await queue.process_one()
    assert r1.outcome == "failed_retry"
    assert store.requeue_calls == [(job.id, 1, "window_llm_failed")]

    r2 = await queue.process_one()
    assert r2.outcome == "failed_retry"
    assert store.requeue_calls[-1] == (job.id, 2, "window_llm_failed")

    r3 = await queue.process_one()
    assert r3.outcome == "failed"
    assert store.failed_calls == [(job.id, "window_llm_failed")]
    assert store.jobs[job.id].status == "failed"


@pytest.mark.asyncio
async def test_process_one_unexpected_error_retries() -> None:
    vip = _vip(123)
    store = FakeQueueStore()
    backfill = FakeBackfill()
    backfill.raise_on_extract = True
    queue = _make_queue(store=store, backfill=backfill, vips=FakeVips([vip]))
    job = await store.enqueue(vip.id, 123)
    assert job is not None

    report = await queue.process_one()

    assert report.outcome == "failed_retry"
    assert store.requeue_calls == [(job.id, 1, "window_unexpected_error")]


# ----------------------------------------------------------------------
# enqueue_missing_vips
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_missing_vips_only_with_history_and_no_profile() -> None:
    a = _vip(1001, name="A")
    b = _vip(1002, name="B")
    c = _vip(1003, name="C")
    d = _vip(1004, name="D")
    e = _vip(1005, name="E")
    store = FakeQueueStore()
    # D: done(empty_history) 1h ago → recent → skip. E: 25h ago → old → enqueue.
    job_d = BackfillJobRecord(
        id=uuid4(), vip_id=d.id, chat_id=d.telegram_user_id, status="done",
        window_index=0, state={}, attempts=0, outcome="empty_history",
        created_at=FAKE_NOW - timedelta(hours=2),
        updated_at=FAKE_NOW - timedelta(hours=1),
    )
    job_e = BackfillJobRecord(
        id=uuid4(), vip_id=e.id, chat_id=e.telegram_user_id, status="done",
        window_index=0, state={}, attempts=0, outcome="empty_history",
        created_at=FAKE_NOW - timedelta(hours=26),
        updated_at=FAKE_NOW - timedelta(hours=25),
    )
    store.jobs[job_d.id] = job_d
    store.jobs[job_e.id] = job_e

    queue = _make_queue(
        store=store,
        vips=FakeVips([a, b, c, d, e]),
        history=FakeHistory({1001: 5, 1003: 5, 1004: 5, 1005: 5}),
        memories=FakeMemories(profiles={c.id}),
    )

    count = await queue.enqueue_missing_vips()

    assert count == 2
    assert store.enqueue_calls == [(a.id, 1001), (e.id, 1005)]
    since = FAKE_NOW - timedelta(hours=24)
    assert store.since_calls == [(a.id, since), (d.id, since), (e.id, since)]
    # B never reached the empty-done guard (no history); C never (has profile).
    assert [v for v, _ in store.since_calls] == [a.id, d.id, e.id]


@pytest.mark.asyncio
async def test_enqueue_missing_vips_disabled_returns_zero() -> None:
    queue = _make_queue(enabled=False)
    assert await queue.enqueue_missing_vips() == 0


# ----------------------------------------------------------------------
# fix round (M1, L4, L5, L8, S2, S-F3, S-F4)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_one_finalize_failed_retries_then_fails() -> None:
    """Fix round (M1): a ``failed`` finalize WITHOUT an exception (e.g. broken
    chat↔vip binding) is a unit failure — retry with backoff and mark the job
    ``failed`` at max_attempts; never a terminal ``done(outcome='failed')``."""
    vip = _vip(123)
    store = FakeQueueStore()
    backfill = FakeBackfill(
        [WindowExtractionResult([_hecho("x")], total_windows=1)] * 3,
        finalize_status="failed",
    )
    queue = _make_queue(
        store=store, backfill=backfill, vips=FakeVips([vip]), max_attempts=3
    )
    job = await store.enqueue(vip.id, 123)
    assert job is not None

    r1 = await queue.process_one()
    assert r1.outcome == "failed_retry"
    assert store.requeue_calls == [(job.id, 1, "finalize_failed")]
    assert store.done_calls == []

    r2 = await queue.process_one()
    assert r2.outcome == "failed_retry"
    assert store.requeue_calls[-1] == (job.id, 2, "finalize_failed")

    r3 = await queue.process_one()
    assert r3.outcome == "failed"
    assert store.failed_calls == [(job.id, "finalize_failed")]
    assert store.jobs[job.id].status == "failed"
    assert store.jobs[job.id].last_error == "finalize_failed"
    assert store.done_calls == []


@pytest.mark.asyncio
async def test_process_one_finalize_disabled_marks_done() -> None:
    """Fix round (M1): flag off mid-run → terminal ``done(outcome='disabled')``,
    not a retry burn and not an ambiguous outcome."""
    vip = _vip(123)
    store = FakeQueueStore()
    backfill = FakeBackfill(
        [WindowExtractionResult([_hecho("x")], total_windows=1)],
        finalize_status="disabled",
    )
    queue = _make_queue(store=store, backfill=backfill, vips=FakeVips([vip]))
    job = await store.enqueue(vip.id, 123)
    assert job is not None

    report = await queue.process_one()

    assert report.outcome == "disabled"
    assert store.done_calls == [(job.id, "disabled")]
    assert store.requeue_calls == []
    assert store.failed_calls == []


@pytest.mark.asyncio
async def test_process_one_invalid_state_fails_with_retries() -> None:
    """Fix round (L4/F6): a corrupt ``state`` jsonb is a unit failure (retry
    → failed with ``state_invalid``), never a job stuck in ``processing``
    until the next restart."""
    vip = _vip(123)
    store = FakeQueueStore()
    backfill = FakeBackfill([WindowExtractionResult([], 1)] * 3)
    queue = _make_queue(
        store=store, backfill=backfill, vips=FakeVips([vip]), max_attempts=3
    )
    job = await store.enqueue(vip.id, 123)
    assert job is not None
    job.state = {"hechos": [{"seccion": "bogus"}]}

    r1 = await queue.process_one()
    assert r1.outcome == "failed_retry"
    assert store.requeue_calls == [(job.id, 1, "state_invalid")]
    assert backfill.extract_window_calls == []  # never reached the service

    r2 = await queue.process_one()
    assert store.requeue_calls[-1] == (job.id, 2, "state_invalid")

    r3 = await queue.process_one()
    assert r3.outcome == "failed"
    assert store.failed_calls == [(job.id, "state_invalid")]
    assert store.jobs[job.id].status == "failed"


@pytest.mark.asyncio
async def test_process_one_attempts_reset_after_successful_window() -> None:
    """Fix round (L5): the retry budget is PER WINDOW — a successful window
    resets ``attempts`` so an early transient failure cannot exhaust the
    retries of every later window of the same run."""
    vip = _vip(123)
    store = FakeQueueStore()
    backfill = FakeBackfill([WindowExtractionResult([_hecho("x")], total_windows=2)])
    queue = _make_queue(store=store, backfill=backfill, vips=FakeVips([vip]))
    job = await store.enqueue(vip.id, 123)
    assert job is not None
    job.attempts = 2  # exhausted budget from a previous window's failures

    report = await queue.process_one()

    assert report.outcome == "window_done"
    assert store.save_calls[-1][3] == 0  # attempts reset


@pytest.mark.asyncio
async def test_process_one_binding_failure_label() -> None:
    """Fix round (L8): a binding failure is labeled ``binding_mismatch``, not
    ``window_llm_failed`` — last_error tells the truth about the cause."""
    vip = _vip(123)
    store = FakeQueueStore()
    backfill = FakeBackfill(
        [
            WindowExtractionResult(
                [], 0, failed=True, failed_reason="binding_mismatch"
            )
        ]
    )
    queue = _make_queue(store=store, backfill=backfill, vips=FakeVips([vip]))
    job = await store.enqueue(vip.id, 123)
    assert job is not None

    report = await queue.process_one()

    assert report.outcome == "failed_retry"
    assert store.requeue_calls == [(job.id, 1, "binding_mismatch")]


@pytest.mark.asyncio
async def test_enqueue_missing_vips_skips_recently_failed() -> None:
    """Fix round (S2): a VIP whose job FAILED in the last 24h is NOT
    re-enqueued automatically (no LLM burn per restart while the provider is
    degraded); the manual ficha button still works (enqueue ignores failed
    rows)."""
    a = _vip(1101, name="A")
    b = _vip(1102, name="B")
    store = FakeQueueStore()
    job_failed = BackfillJobRecord(
        id=uuid4(), vip_id=a.id, chat_id=a.telegram_user_id, status="failed",
        window_index=0, state={}, attempts=2, last_error="window_llm_failed",
        created_at=FAKE_NOW - timedelta(hours=2),
        updated_at=FAKE_NOW - timedelta(hours=1),
    )
    store.jobs[job_failed.id] = job_failed

    queue = _make_queue(
        store=store,
        vips=FakeVips([a, b]),
        history=FakeHistory({1101: 5, 1102: 5}),
    )

    count = await queue.enqueue_missing_vips()

    assert count == 1
    assert store.enqueue_calls == [(b.id, 1102)]
    since = FAKE_NOW - timedelta(hours=24)
    assert store.since_failed_calls == [(a.id, since), (b.id, since)]


@pytest.mark.asyncio
async def test_schedule_enqueue_keeps_task_reference() -> None:
    """Fix round (S-F4): the fire-and-forget task is kept in the queue's task
    set (with done-callback cleanup) so GC cannot collect it mid-flight."""
    vip = _vip(123, name="Ana")
    store = FakeQueueStore()
    queue = _make_queue(
        store=store,
        vips=FakeVips([vip]),
        history=FakeHistory({123: 5}),
    )

    queue.schedule_enqueue(123)

    assert len(queue._tasks) == 1
    task = next(iter(queue._tasks))
    assert task.get_name() == "backfill-enqueue-123"
    await asyncio.gather(task)
    assert len(queue._tasks) == 0  # done callback cleaned up
    assert store.enqueue_calls == [(vip.id, 123)]


@pytest.mark.asyncio
async def test_recover_stale_forwards_max_age() -> None:
    """Fix round (S-F3): the queue passes the age limit through to the store."""
    store = FakeQueueStore()
    queue = _make_queue(store=store)
    max_age = timedelta(hours=2)
    await queue.recover_stale(max_age=max_age)
    assert store.recover_max_ages == [max_age]


@pytest.mark.asyncio
async def test_enqueue_uses_history_count_not_full_read() -> None:
    """Fix round (L6/F7): the step estimator uses count(*) — the full history
    is never materialized just for the DM text."""
    vip = _vip(123, name="Ana")
    store = FakeQueueStore()
    history = FakeHistory({123: 450})
    queue = _make_queue(
        store=store, vips=FakeVips([vip]), history=history, notifier=FakeNotifier()
    )

    report = await queue.enqueue_by_telegram_user(123)

    assert report.status == "enqueued"
    assert report.steps == 3  # ceil(450 / 200)
    assert history.count_calls == [123]
    assert history.calls == []  # list_all never called for the estimator
