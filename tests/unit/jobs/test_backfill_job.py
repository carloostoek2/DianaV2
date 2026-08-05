"""BackfillJob unit tests — fakes only, NO real sleeps (injectable sleep)."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import timedelta
from uuid import uuid4

import pytest

from diana.application.memory_backfill_queue import ProcessReport
from diana.jobs.backfill import BackfillJob


class FakeSleep:
    """Coroutine sleep double: records durations, returns immediately."""

    def __init__(self) -> None:
        self.durations: list[float] = []

    async def __call__(self, duration: float) -> None:
        self.durations.append(duration)
        await asyncio.sleep(0)


class FakeQueue:
    """MemoryBackfillQueue double with scripted process_one reports."""

    def __init__(self, reports: list[ProcessReport] | None = None) -> None:
        self._reports: deque[ProcessReport] = deque(reports or [])
        self.process_calls = 0
        self.recover_calls = 0
        self.recover_max_ages: list[timedelta | None] = []
        self.raise_on_process = False

    async def recover_stale(self, *, max_age: timedelta | None = None) -> int:
        self.recover_calls += 1
        self.recover_max_ages.append(max_age)
        return 2

    async def process_one(self) -> ProcessReport:
        self.process_calls += 1
        if self.raise_on_process:
            raise RuntimeError("fake process_one boom")
        if self._reports:
            return self._reports.popleft()
        return ProcessReport(status="idle")


async def _wait_until(pred, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not pred():
        if loop.time() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.01)


def _make_job(
    queue: FakeQueue,
    sleep: FakeSleep,
    *,
    interval_seconds: int = 3600,
    idle_poll_seconds: int = 60,
    recover_stale_max_age_sec: int = 3600,
    wake: asyncio.Event | None = None,
) -> BackfillJob:
    return BackfillJob(
        queue,  # type: ignore[arg-type]
        interval_seconds=interval_seconds,
        idle_poll_seconds=idle_poll_seconds,
        recover_stale_max_age_sec=recover_stale_max_age_sec,
        wake=wake,
        sleep=sleep,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_job_sleeps_interval_after_processed_unit() -> None:
    queue = FakeQueue(
        [
            ProcessReport(status="processed", vip_id=uuid4(), outcome="ok"),
            ProcessReport(status="idle"),
        ]
    )
    sleep = FakeSleep()
    job = _make_job(queue, sleep, interval_seconds=3600, idle_poll_seconds=60)

    task = asyncio.create_task(job.start())
    await _wait_until(lambda: 3600.0 in sleep.durations)
    await job.stop()
    await task

    assert sleep.durations[0] == 3600.0
    assert queue.process_calls >= 2


@pytest.mark.asyncio
async def test_job_waits_idle_poll_when_idle_no_wake() -> None:
    queue = FakeQueue([ProcessReport(status="idle")])
    sleep = FakeSleep()
    job = _make_job(queue, sleep, interval_seconds=3600, idle_poll_seconds=60)

    task = asyncio.create_task(job.start())
    await _wait_until(lambda: 60.0 in sleep.durations)
    await job.stop()
    await task

    assert sleep.durations[0] == 60.0


@pytest.mark.asyncio
async def test_job_wake_event_breaks_idle_wait() -> None:
    queue = FakeQueue([ProcessReport(status="idle")])
    wake = asyncio.Event()
    sleep = FakeSleep()
    job = _make_job(queue, sleep, idle_poll_seconds=60, wake=wake)

    task = asyncio.create_task(job.start())
    # First cycle: process_one → idle → job waits on the wake event.
    await _wait_until(lambda: queue.process_calls >= 1)
    # Setting the wake event must unblock the idle wait immediately (no 60s poll).
    wake.set()
    await _wait_until(lambda: queue.process_calls >= 2)
    await job.stop()
    wake.set()  # unblock the pending idle wait so the loop sees the stop flag
    await task

    assert queue.process_calls >= 2


@pytest.mark.asyncio
async def test_job_stop_breaks_loop() -> None:
    queue = FakeQueue([ProcessReport(status="idle")])
    sleep = FakeSleep()
    job = _make_job(queue, sleep, idle_poll_seconds=60)

    task = asyncio.create_task(job.start())
    await _wait_until(lambda: len(sleep.durations) >= 1)
    await job.stop()
    await asyncio.wait_for(task, timeout=2.0)

    n = queue.process_calls
    await asyncio.sleep(0.05)
    assert queue.process_calls == n  # no iterations after stop


@pytest.mark.asyncio
async def test_job_recover_stale_at_start() -> None:
    queue = FakeQueue([])
    sleep = FakeSleep()
    job = _make_job(queue, sleep, idle_poll_seconds=60)

    task = asyncio.create_task(job.start())
    await _wait_until(lambda: queue.recover_calls == 1)
    await job.stop()
    await task

    assert queue.recover_calls == 1


@pytest.mark.asyncio
async def test_job_recover_stale_forwards_configured_max_age() -> None:
    """Fix round (S-F3): the configured age limit reaches the queue/store."""
    queue = FakeQueue([])
    sleep = FakeSleep()
    job = _make_job(
        queue, sleep, idle_poll_seconds=60, recover_stale_max_age_sec=7200
    )

    task = asyncio.create_task(job.start())
    await _wait_until(lambda: queue.recover_calls == 1)
    await job.stop()
    await task

    assert queue.recover_max_ages == [timedelta(seconds=7200)]


@pytest.mark.asyncio
async def test_job_swallows_cycle_error() -> None:
    queue = FakeQueue([])
    queue.raise_on_process = True
    sleep = FakeSleep()
    job = _make_job(queue, sleep, idle_poll_seconds=60)

    task = asyncio.create_task(job.start())
    # The loop must keep iterating after a process_one exception.
    await _wait_until(lambda: queue.process_calls >= 2)
    await job.stop()
    await task

    assert queue.process_calls >= 2
