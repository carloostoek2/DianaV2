"""MetricsJob — weekly learning_metrics aggregation loop (application only)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from diana.application.metrics_service import MetricsAggregationService

logger = logging.getLogger("diana.jobs")

__all__ = ["MetricsJob", "run_weekly_metrics"]


async def run_weekly_metrics(
    service: MetricsAggregationService,
    week_start: date | None = None,
) -> dict[str, Any]:
    """One-shot aggregate_week; never raises out. Returns a small report dict."""
    try:
        report = await service.aggregate_week(week_start)
    except Exception:
        logger.exception("metrics_run_error")
        return {"status": "error", "error": 1}

    metrics = report.metrics
    week_label = (
        metrics.week_start.isoformat()
        if metrics is not None
        else (week_start.isoformat() if week_start else None)
    )
    total = int(metrics.total_turns) if metrics is not None else 0
    out: dict[str, Any] = {
        "status": report.status,
        "week_start": week_label,
        "total_turns": total,
    }
    logger.info(
        "metrics_run_complete",
        extra={
            "status": report.status,
            "week_start": week_label,
            "total_turns": total,
        },
    )
    return out


class MetricsJob:
    """Periodically aggregate the previous complete ISO week.

    Each tick calls ``maybe_run()``: if UTC now is past Monday 03:00 and the
    last successful week_start is older than the previous Monday, run
    ``aggregate_week(previous_monday)``. Last success is in-memory only (v1).

    ``start()`` is one-shot — after ``stop()``, create a new instance to restart.
    """

    def __init__(
        self,
        service: MetricsAggregationService,
        *,
        interval_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._interval = interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop_event = asyncio.Event()
        self._last_success_week: date | None = None

    async def start(self) -> None:
        """Run the metrics loop until stop() is called."""
        logger.info(
            "metrics_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                await asyncio.wait_for(
                    self.maybe_run(),
                    timeout=self._interval,
                )
                elapsed = time.monotonic() - t0
                logger.debug(
                    "metrics_job_tick",
                    extra={"duration_ms": int(elapsed * 1000)},
                )
            except TimeoutError:
                logger.warning("metrics_run_timeout")
            except Exception:
                logger.exception("metrics_run_error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
                break
            except TimeoutError:
                continue

        logger.info("metrics_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on the next iteration."""
        self._stop_event.set()
        logger.debug("metrics_job_stop_signalled")

    async def maybe_run(self) -> dict[str, Any] | None:
        """Run aggregation when past Monday 03:00 and week not yet done."""
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        prev_week = self._service.previous_complete_week_start(now)
        if self._last_success_week is not None and self._last_success_week >= prev_week:
            return None

        # Gate: after Monday 03:00 UTC of the week following prev_week.
        gate = datetime(
            prev_week.year,
            prev_week.month,
            prev_week.day,
            3,
            0,
            0,
            tzinfo=UTC,
        ) + timedelta(days=7)
        if now < gate:
            return None

        result = await run_weekly_metrics(self._service, prev_week)
        if result.get("status") != "error":
            self._last_success_week = prev_week
        return result
