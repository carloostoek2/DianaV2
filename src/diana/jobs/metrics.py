"""MetricsJob — weekly learning_metrics aggregation loop (application only)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from diana.application.metrics_service import MetricsAggregationService
from diana.application.mexico_tz import cdmx_local_date

logger = logging.getLogger("diana.jobs")

__all__ = [
    "AtencionCountsSource",
    "MetricsJob",
    "run_weekly_metrics",
    "METRICS_LAST_SUCCESS_WEEK_KEY",
]

METRICS_LAST_SUCCESS_WEEK_KEY = "metrics.last_success_week"


class MetricsJobConfigStore(Protocol):
    async def get(self, key: str) -> object | None: ...

    async def set(self, key: str, value: object) -> None: ...


class AtencionCountsSource(Protocol):
    """Real-SQL counters for the daily atencion log (REQ-ATN-14)."""

    async def count_atencion_turns_since(self, since_utc: datetime) -> int: ...

    async def count_atencion_limit_reached_on(self, fecha_local: date) -> int: ...


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


def _parse_week_marker(raw: object) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


class MetricsJob:
    """Periodically aggregate the previous complete ISO week.

    Each tick calls ``maybe_run()``: if UTC now is past Monday 03:00 and the
    last successful week_start is older than the previous Monday, run
    ``aggregate_week(previous_monday)``.

    When ``config`` is provided, last success is durable under
    ``metrics.last_success_week`` (ISO date string). Without config, state is
    in-memory only (process-local).

    ``start()`` is one-shot — after ``stop()``, create a new instance to restart.
    """

    def __init__(
        self,
        service: MetricsAggregationService,
        *,
        interval_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
        config: MetricsJobConfigStore | None = None,
        atencion_counts: AtencionCountsSource | None = None,
    ) -> None:
        self._service = service
        self._interval = interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._config = config
        self._atencion_counts = atencion_counts
        self._stop_event = asyncio.Event()
        self._last_success_week: date | None = None
        self._loaded_from_config = False
        self._last_atencion_log_day: date | None = None

    async def _ensure_loaded(self) -> None:
        if self._loaded_from_config or self._config is None:
            return
        self._loaded_from_config = True
        try:
            raw = await self._config.get(METRICS_LAST_SUCCESS_WEEK_KEY)
        except Exception:
            logger.exception("metrics_last_success_week_load_failed")
            return
        parsed = _parse_week_marker(raw)
        if parsed is not None:
            self._last_success_week = parsed

    async def _persist_success(self, week: date) -> None:
        self._last_success_week = week
        if self._config is None:
            return
        try:
            await self._config.set(METRICS_LAST_SUCCESS_WEEK_KEY, week.isoformat())
        except Exception:
            logger.exception(
                "metrics_last_success_week_persist_failed",
                extra={"week_start": week.isoformat()},
            )

    async def _log_atencion_daily_counts(self) -> None:
        """Log atencion turn / cap counters once per local calendar day.

        Read-only and fail-soft: any source error is logged and swallowed, so
        a DB hiccup never breaks the metrics loop (REQ-ATN-14).
        """
        if self._atencion_counts is None:
            return
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        fecha_local = cdmx_local_date(now)
        if self._last_atencion_log_day is not None and self._last_atencion_log_day == fecha_local:
            return
        try:
            since_utc = now - timedelta(days=1)
            turns = await self._atencion_counts.count_atencion_turns_since(since_utc)
            caps = await self._atencion_counts.count_atencion_limit_reached_on(fecha_local)
        except Exception:
            logger.exception("atencion_daily_metrics_failed")
            return
        self._last_atencion_log_day = fecha_local
        logger.info(
            "atencion_daily_metrics",
            extra={
                "fecha_local": fecha_local.isoformat(),
                "atencion_turns_today": int(turns),
                "limit_reached_chats_today": int(caps),
            },
        )

    async def start(self) -> None:
        """Run the metrics loop until stop() is called."""
        logger.info(
            "metrics_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                await self._log_atencion_daily_counts()
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
        await self._ensure_loaded()
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
            await self._persist_success(prev_week)
        return result
