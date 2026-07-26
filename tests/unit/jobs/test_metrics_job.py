"""MetricsJob + run_weekly_metrics unit tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest

from diana.jobs.metrics import MetricsJob, run_weekly_metrics


@dataclass
class FakeReport:
    status: str
    metrics: Any


class FakeWeekMetrics:
    def __init__(self, week_start: date, total_turns: int = 0) -> None:
        self.week_start = week_start
        self.total_turns = total_turns


class FakeMetricsService:
    def __init__(self) -> None:
        self.calls: list[date | None] = []
        self._error = False
        self._report = FakeReport(
            status="ok",
            metrics=FakeWeekMetrics(date(2026, 7, 13), total_turns=3),
        )
        self._prev_week = date(2026, 7, 13)
        self._last_success_calls: list[date] = []

    def set_error(self, value: bool = True) -> None:
        self._error = value

    def set_report(self, report: FakeReport) -> None:
        self._report = report

    async def aggregate_week(self, week_start: date | None = None) -> FakeReport:
        self.calls.append(week_start)
        if self._error:
            raise RuntimeError("aggregate boom")
        return self._report

    def previous_complete_week_start(
        self, now: datetime | None = None
    ) -> date:
        return self._prev_week


@pytest.mark.asyncio
async def test_run_weekly_metrics_calls_service_and_returns_dict() -> None:
    svc = FakeMetricsService()
    out = await run_weekly_metrics(svc)  # type: ignore[arg-type]
    assert svc.calls == [None]
    assert out["status"] == "ok"
    assert out["week_start"] == "2026-07-13"
    assert out["total_turns"] == 3


@pytest.mark.asyncio
async def test_run_weekly_metrics_with_explicit_week() -> None:
    svc = FakeMetricsService()
    week = date(2026, 7, 6)
    svc.set_report(
        FakeReport(status="empty", metrics=FakeWeekMetrics(week, total_turns=0))
    )
    out = await run_weekly_metrics(svc, week)  # type: ignore[arg-type]
    assert svc.calls == [week]
    assert out["status"] == "empty"
    assert out["total_turns"] == 0


@pytest.mark.asyncio
async def test_run_weekly_metrics_swallows_errors() -> None:
    svc = FakeMetricsService()
    svc.set_error(True)
    out = await run_weekly_metrics(svc)  # type: ignore[arg-type]
    assert out["status"] == "error"
    assert out.get("error") == 1


@pytest.mark.asyncio
async def test_job_start_stop_runs_loop() -> None:
    svc = FakeMetricsService()
    # Force maybe_run: set clock past Monday 03:00 with no prior success
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=0.05,
        clock=lambda: datetime(2026, 7, 20, 4, 0, tzinfo=UTC),
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())
    assert len(svc.calls) >= 1


@pytest.mark.asyncio
async def test_job_handles_run_errors_and_continues() -> None:
    svc = FakeMetricsService()
    svc.set_error(True)
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=0.05,
        clock=lambda: datetime(2026, 7, 20, 4, 0, tzinfo=UTC),
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())


@pytest.mark.asyncio
async def test_job_skips_when_already_ran_for_previous_week() -> None:
    svc = FakeMetricsService()
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=0.05,
        clock=lambda: datetime(2026, 7, 20, 4, 0, tzinfo=UTC),
    )
    job._last_success_week = date(2026, 7, 13)  # noqa: SLF001

    async def _stop_soon() -> None:
        await asyncio.sleep(0.1)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())
    assert svc.calls == []


@pytest.mark.asyncio
async def test_job_skips_before_monday_0300() -> None:
    svc = FakeMetricsService()
    # Monday 02:00 — before 03:00 gate
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=0.05,
        clock=lambda: datetime(2026, 7, 20, 2, 0, tzinfo=UTC),
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.1)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())
    assert svc.calls == []


@pytest.mark.asyncio
async def test_pre_stopped_job_does_not_run() -> None:
    svc = FakeMetricsService()
    job = MetricsJob(svc, interval_seconds=0.05)  # type: ignore[arg-type]
    await job.stop()
    await job.start()
    assert svc.calls == []
