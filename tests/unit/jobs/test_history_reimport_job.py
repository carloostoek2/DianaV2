"""HistoryReimportJob unit tests — fakes only, NO real sleeps (injectable sleep)."""

from __future__ import annotations

import asyncio

import pytest

from diana.application.history_reimport import ReimportReport
from diana.jobs.history_reimport import HistoryReimportJob


class FakeSleep:
    """Coroutine sleep double: records durations, returns immediately."""

    def __init__(self) -> None:
        self.durations: list[float] = []

    async def __call__(self, duration: float) -> None:
        self.durations.append(duration)
        await asyncio.sleep(0)


class FakeService:
    """HistoryReimportService double with scripted process_next reports."""

    def __init__(self, reports: list[ReimportReport] | None = None) -> None:
        self._reports: list[ReimportReport] = list(reports or [])
        self.process_calls = 0
        self.raise_on_process = False

    async def process_next(self) -> ReimportReport:
        self.process_calls += 1
        if self.raise_on_process:
            raise RuntimeError("fake process_next boom")
        if self._reports:
            return self._reports.pop(0)
        return ReimportReport(status="no_vip")


async def _wait_until(pred, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not pred():
        if loop.time() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_job_sleeps_interval_after_processed_unit() -> None:
    service = FakeService([ReimportReport(status="processed", telegram_user_id=42)])
    sleep = FakeSleep()
    job = HistoryReimportJob(
        service,  # type: ignore[arg-type]
        interval_seconds=3600,
        idle_poll_seconds=60,
        sleep=sleep,  # type: ignore[arg-type]
    )
    task = asyncio.create_task(job.start())
    await _wait_until(lambda: 3600.0 in sleep.durations)
    await job.stop()
    await task
    assert sleep.durations[0] == 3600.0
    assert service.process_calls >= 2


@pytest.mark.asyncio
async def test_job_idle_polls_when_no_vips() -> None:
    service = FakeService([ReimportReport(status="no_vip")])
    sleep = FakeSleep()
    job = HistoryReimportJob(
        service,  # type: ignore[arg-type]
        interval_seconds=3600,
        idle_poll_seconds=60,
        sleep=sleep,  # type: ignore[arg-type]
    )
    task = asyncio.create_task(job.start())
    await _wait_until(lambda: 60.0 in sleep.durations)
    await job.stop()
    await task
    assert sleep.durations[0] == 60.0


@pytest.mark.asyncio
async def test_job_stop_breaks_loop() -> None:
    service = FakeService([])
    sleep = FakeSleep()
    job = HistoryReimportJob(
        service,  # type: ignore[arg-type]
        interval_seconds=3600,
        idle_poll_seconds=60,
        sleep=sleep,  # type: ignore[arg-type]
    )
    task = asyncio.create_task(job.start())
    await _wait_until(lambda: len(sleep.durations) >= 1)
    await job.stop()
    await asyncio.wait_for(task, timeout=2.0)
    n = service.process_calls
    await asyncio.sleep(0.05)
    assert service.process_calls == n  # no iterations after stop


@pytest.mark.asyncio
async def test_job_swallows_cycle_error() -> None:
    service = FakeService([])
    service.raise_on_process = True
    sleep = FakeSleep()
    job = HistoryReimportJob(
        service,  # type: ignore[arg-type]
        interval_seconds=3600,
        idle_poll_seconds=60,
        sleep=sleep,  # type: ignore[arg-type]
    )
    task = asyncio.create_task(job.start())
    await _wait_until(lambda: service.process_calls >= 2)
    await job.stop()
    await task
    assert service.process_calls >= 2
