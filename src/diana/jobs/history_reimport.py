"""HistoryReimportJob — scheduler for the slow VIP history re-import.

One VIP per cycle: after a processed unit the job sleeps
``history_reimport_interval_sec`` (settings, default 3600) — the same pacing
as the backfill scheduler, so the owner's personal Telegram session is never
hit more than once per hour (account protection against aggressive moves).

Jobs delegate to application services (AGENTS.md §2.1): this module has no
import or cognitive logic — it only drives ``HistoryReimportService``. The
``sleep`` callable is injectable so unit tests never sleep for real.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from diana.application.history_reimport import HistoryReimportService

logger = logging.getLogger("diana.jobs")

__all__ = ["HistoryReimportJob"]


class HistoryReimportJob:
    """Loop that re-imports one VIP per cycle, interval-spaced."""

    def __init__(
        self,
        service: HistoryReimportService,
        *,
        interval_seconds: int = 3600,
        idle_poll_seconds: int = 60,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._service = service
        self._interval = max(1, int(interval_seconds))
        self._idle_poll = max(1, int(idle_poll_seconds))
        self._sleep = sleep or asyncio.sleep
        self._stop = asyncio.Event()

    async def start(self) -> None:
        """Run the re-import loop until ``stop()`` is called (one-shot)."""
        logger.info(
            "history_reimport_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop.is_set():
            try:
                report = await self._service.process_next()
            except Exception:
                logger.exception("history_reimport_cycle_error")
                report = None
            if report is not None and report.status == "processed":
                # Account protection: one VIP per interval (default 1 hour).
                await self._sleep(float(self._interval))
            else:
                # No active VIPs — idle-poll; new VIPs resume the rotation.
                await self._sleep(float(self._idle_poll))
        logger.info("history_reimport_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on its next iteration."""
        self._stop.set()
        logger.debug("history_reimport_job_stop_signalled")
