"""MetricsJob + run_weekly_metrics unit tests."""

from __future__ import annotations

import asyncio
import logging
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



class FakeConfigStore:
    def __init__(self) -> None:
        self.kv: dict[str, object] = {}
        self.sets: list[tuple[str, object]] = []

    async def get(self, key: str) -> object | None:
        return self.kv.get(key)

    async def set(self, key: str, value: object) -> None:
        self.sets.append((key, value))
        self.kv[key] = value


@pytest.mark.asyncio
async def test_job_persists_last_success_week_in_config() -> None:
    """R4: successful maybe_run writes metrics.last_success_week ISO date."""
    svc = FakeMetricsService()
    cfg = FakeConfigStore()
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=3600,
        clock=lambda: datetime(2026, 7, 20, 4, 0, tzinfo=UTC),
        config=cfg,  # type: ignore[arg-type]
    )
    out = await job.maybe_run()
    assert out is not None
    assert out["status"] == "ok"
    assert cfg.kv.get("metrics.last_success_week") == "2026-07-13"


@pytest.mark.asyncio
async def test_job_loads_last_success_week_from_config_skips_rerun() -> None:
    """R4: new job instance with durable marker skips already-done week."""
    svc = FakeMetricsService()
    cfg = FakeConfigStore()
    cfg.kv["metrics.last_success_week"] = "2026-07-13"
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=3600,
        clock=lambda: datetime(2026, 7, 20, 4, 0, tzinfo=UTC),
        config=cfg,  # type: ignore[arg-type]
    )
    out = await job.maybe_run()
    assert out is None
    assert svc.calls == []


@pytest.mark.asyncio
async def test_job_without_config_keeps_in_memory_behavior() -> None:
    """R4: config=None remains in-memory only (backward compatible)."""
    svc = FakeMetricsService()
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=3600,
        clock=lambda: datetime(2026, 7, 20, 4, 0, tzinfo=UTC),
    )
    out1 = await job.maybe_run()
    assert out1 is not None
    out2 = await job.maybe_run()
    assert out2 is None
    assert len(svc.calls) == 1


class FakeAtencionCounts:
    """In-memory AtencionCountsSource (REQ-ATN-14 daily log)."""

    def __init__(self, *, turns: int = 0, caps: int = 0, error: bool = False) -> None:
        self.turns = turns
        self.caps = caps
        self.error = error
        self.turns_calls: list[datetime] = []
        self.caps_calls: list[date] = []

    async def count_atencion_turns_since(self, since_utc: datetime) -> int:
        self.turns_calls.append(since_utc)
        if self.error:
            raise RuntimeError("turns boom")
        return self.turns

    async def count_atencion_limit_reached_on(self, fecha_local: date) -> int:
        self.caps_calls.append(fecha_local)
        if self.error:
            raise RuntimeError("caps boom")
        return self.caps


@pytest.mark.asyncio
async def test_log_atencion_daily_counts_logs_once_per_local_day(caplog) -> None:
    """REQ-ATN-14: counters read once and logged once per CDMX civil day."""
    svc = FakeMetricsService()
    counts = FakeAtencionCounts(turns=3, caps=1)
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=3600,
        clock=lambda: datetime(2026, 7, 20, 15, 0, tzinfo=UTC),
        atencion_counts=counts,  # type: ignore[arg-type]
    )
    with caplog.at_level(logging.INFO, logger="diana.jobs"):
        await job._log_atencion_daily_counts()  # noqa: SLF001
        await job._log_atencion_daily_counts()  # noqa: SLF001

    assert len(counts.turns_calls) == 1
    assert len(counts.caps_calls) == 1
    records = [r for r in caplog.records if r.getMessage() == "atencion_daily_metrics"]
    assert len(records) == 1
    assert records[0].__dict__["atencion_turns_today"] == 3
    assert records[0].__dict__["limit_reached_chats_today"] == 1


@pytest.mark.asyncio
async def test_log_atencion_daily_counts_source_error_fail_soft(caplog) -> None:
    """A source failure is swallowed; the metrics loop must not break."""
    svc = FakeMetricsService()
    counts = FakeAtencionCounts(error=True)
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=3600,
        clock=lambda: datetime(2026, 7, 20, 15, 0, tzinfo=UTC),
        atencion_counts=counts,  # type: ignore[arg-type]
    )
    with caplog.at_level(logging.WARNING, logger="diana.jobs"):
        await job._log_atencion_daily_counts()  # noqa: SLF001

    assert any(
        r.getMessage() == "atencion_daily_metrics_failed" for r in caplog.records
    )


@pytest.mark.asyncio
async def test_log_atencion_daily_counts_retries_after_error(caplog) -> None:
    """F13: a failed source read does not mark the day done → next tick retries."""
    svc = FakeMetricsService()
    counts = FakeAtencionCounts(error=True)
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=3600,
        clock=lambda: datetime(2026, 7, 20, 15, 0, tzinfo=UTC),
        atencion_counts=counts,  # type: ignore[arg-type]
    )
    with caplog.at_level(logging.INFO, logger="diana.jobs"):
        await job._log_atencion_daily_counts()  # noqa: SLF001  → fails
        counts.error = False
        await job._log_atencion_daily_counts()  # noqa: SLF001  → succeeds

    records = [r for r in caplog.records if r.getMessage() == "atencion_daily_metrics"]
    assert len(records) == 1
    assert len(counts.turns_calls) == 2


@pytest.mark.asyncio
async def test_log_atencion_daily_counts_resets_on_new_local_day(caplog) -> None:
    """F13: a new CDMX civil day logs a fresh row; same day stays deduped.

    Also asserts the "today" window is anchored at the CDMX local midnight
    (06:00 UTC for CDMX) rather than a rolling 24h span (F3).
    """
    svc = FakeMetricsService()
    counts = FakeAtencionCounts(turns=3, caps=1)
    times = [
        datetime(2026, 7, 20, 15, 0, tzinfo=UTC),  # CDMX day 1
        datetime(2026, 7, 21, 15, 0, tzinfo=UTC),  # CDMX day 2
        datetime(2026, 7, 21, 20, 0, tzinfo=UTC),  # CDMX day 2 again → skip
    ]
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=3600,
        atencion_counts=counts,  # type: ignore[arg-type]
        clock=lambda: times.pop(0),
    )
    with caplog.at_level(logging.INFO, logger="diana.jobs"):
        await job._log_atencion_daily_counts()  # noqa: SLF001
        await job._log_atencion_daily_counts()  # noqa: SLF001
        await job._log_atencion_daily_counts()  # noqa: SLF001

    records = [r for r in caplog.records if r.getMessage() == "atencion_daily_metrics"]
    assert len(records) == 2
    assert len(counts.turns_calls) == 2
    assert counts.turns_calls[0] == datetime(2026, 7, 20, 6, 0, tzinfo=UTC)
    assert counts.turns_calls[1] == datetime(2026, 7, 21, 6, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_log_atencion_daily_counts_without_source_is_noop(caplog) -> None:
    """Backward compat: no atencion_counts wired → helper is a no-op."""
    svc = FakeMetricsService()
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=3600,
        clock=lambda: datetime(2026, 7, 20, 15, 0, tzinfo=UTC),
    )
    with caplog.at_level(logging.INFO, logger="diana.jobs"):
        await job._log_atencion_daily_counts()  # noqa: SLF001

    assert not any(
        r.getMessage() == "atencion_daily_metrics" for r in caplog.records
    )


@pytest.mark.asyncio
async def test_job_start_logs_atencion_daily_counts() -> None:
    """start() drives the daily atencion log each loop iteration."""
    svc = FakeMetricsService()
    counts = FakeAtencionCounts(turns=2, caps=1)
    job = MetricsJob(
        svc,  # type: ignore[arg-type]
        interval_seconds=0.05,
        clock=lambda: datetime(2026, 7, 20, 4, 0, tzinfo=UTC),
        atencion_counts=counts,  # type: ignore[arg-type]
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())
    assert len(counts.turns_calls) == 1
    assert len(counts.caps_calls) == 1
