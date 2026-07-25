"""TracePurgeJob — periodic TTL-based purge of expired pipeline traces."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("diana.jobs")


class TracePurgeJob:
    """Periodically delete expired pipeline_traces rows.

    ``start()`` is one-shot — once it returns (after ``stop()`` is called),
    the instance cannot be restarted. Create a new instance if needed.
    """

    def __init__(
        self,
        trace_store: Any,
        *,
        interval_seconds: int = 3600,
    ) -> None:
        self._store = trace_store
        self._interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the purge loop until stop() is called.

        One-shot: calling start() after stop() will return immediately
        since the stop event is already set.
        """
        logger.info(
            "purge_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                deleted = await asyncio.wait_for(
                    self._store.purge_expired(),
                    timeout=self._interval,
                )
                if deleted:
                    elapsed = time.monotonic() - t0
                    logger.info(
                        "purge_run_complete",
                        extra={
                            "deleted": deleted,
                            "duration_ms": int(elapsed * 1000),
                        },
                    )
                else:
                    logger.debug(
                        "purge_run_noop",
                        extra={"interval_seconds": self._interval},
                    )
            except TimeoutError:
                logger.warning("purge_run_timeout")
            except Exception:
                logger.exception("purge_run_error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
                break  # stop event was set during the timeout
            except TimeoutError:
                continue  # normal interval elapsed

        logger.info("purge_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on the next iteration."""
        self._stop_event.set()
        logger.debug("purge_job_stop_signalled")


__all__ = ["TracePurgeJob"]
