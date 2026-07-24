"""GrayZoneExpirationJob — periodic expiration of stale doctrinal queries."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger("diana.jobs")


class GrayZoneExpirationJob:
    """Periodically call gray_zone.expire_old_queries() to clean stale queries.

    Runs until stop() is called. Uses asyncio.Event for clean shutdown.
    """

    def __init__(
        self,
        gray_zone: Any,
        notifier: Any,
        *,
        interval_seconds: int = 300,
    ) -> None:
        self._gray_zone = gray_zone
        self._notifier = notifier
        self._interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the expiration loop until stop() is called."""
        logger.info(
            "expiration_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            try:
                expired = await self._gray_zone.expire_old_queries()
                if expired:
                    logger.info(
                        "expiration_run_complete",
                        extra={"expired_count": len(expired)},
                    )
                else:
                    logger.debug(
                        "expiration_run_noop",
                        extra={"interval_seconds": self._interval},
                    )
            except Exception:
                logger.exception("expiration_run_error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
                break  # stop event was set during the timeout
            except TimeoutError:
                continue  # normal interval elapsed

        logger.info("expiration_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on the next iteration."""
        self._stop_event.set()
        logger.debug("expiration_job_stop_signalled")


__all__ = ["GrayZoneExpirationJob"]
