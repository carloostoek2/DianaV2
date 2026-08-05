"""BackfillJob — scheduler for the VIP profile backfill queue (REQ-MEM-05).

One transcript window per cycle: after a processed unit the job sleeps
``backfill_interval_sec`` (settings, default 3600) — between VIPs AND between
windows of the same VIP (account protection). When the queue is empty it
idle-polls every ``idle_poll_seconds`` unless a shared wake event is set
(``enqueue`` sets it so the first unit starts immediately — R2). Crash
recovery (``recover_stale``) runs once at startup.

Jobs delegate to application services (AGENTS.md §2.1): this module has no
extraction or cognitive logic — it only drives ``MemoryBackfillQueue``.
The ``sleep`` callable is injectable so unit tests never sleep for real.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from diana.application.memory_backfill_queue import MemoryBackfillQueue

logger = logging.getLogger("diana.jobs")

__all__ = ["BackfillJob"]


class BackfillJob:
    """Loop that processes one backfill unit per cycle, interval-spaced."""

    def __init__(
        self,
        queue: MemoryBackfillQueue,
        *,
        interval_seconds: int = 3600,
        idle_poll_seconds: int = 60,
        recover_stale_max_age_sec: int = 3600,
        wake: asyncio.Event | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._queue = queue
        self._interval = max(1, int(interval_seconds))
        self._idle_poll = max(1, int(idle_poll_seconds))
        self._recover_stale_max_age = max(1, int(recover_stale_max_age_sec))
        self._wake = wake
        self._sleep = sleep or asyncio.sleep
        self._stop = asyncio.Event()

    async def start(self) -> None:
        """Run the backfill loop until ``stop()`` is called (one-shot)."""
        try:
            recovered = await self._queue.recover_stale(
                max_age=timedelta(seconds=self._recover_stale_max_age)
            )
        except Exception:
            logger.exception("backfill_recover_stale_failed")
            recovered = 0
        logger.info(
            "backfill_job_started",
            extra={"interval_seconds": self._interval, "recovered": recovered},
        )
        while not self._stop.is_set():
            try:
                report = await self._queue.process_one()
            except Exception:
                logger.exception("backfill_cycle_error")
                report = None
            if report is not None and report.status == "processed":
                # Account protection: BACKFILL_INTERVAL_SEC between EVERY unit
                # (between VIPs AND between windows of the same VIP).
                await self._sleep(float(self._interval))
            elif self._wake is not None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(
                        self._wake.wait(), timeout=self._idle_poll
                    )
                except TimeoutError:
                    pass
            else:
                await self._sleep(float(self._idle_poll))
        logger.info("backfill_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on its next iteration."""
        self._stop.set()
        logger.debug("backfill_job_stop_signalled")
