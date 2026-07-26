"""RecontactJob — periodic due-VIP recontact loop (application service only)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from diana.application.recontact_service import RecontactService

logger = logging.getLogger("diana.jobs")


async def run_due_recontacts(service: RecontactService) -> dict[str, int]:
    """One-shot: get_due_vips → execute each; return counts by status. Never raises out."""
    counts: dict[str, int] = {"total": 0}
    try:
        due = await service.get_due_vips()
    except Exception:
        logger.exception("recontact_get_due_failed")
        return {"total": 0, "error": 1}

    for vip_id in due:
        counts["total"] += 1
        try:
            status = await service.execute_recontact(vip_id)
        except Exception:
            logger.exception(
                "recontact_execute_error",
                extra={"vip_id": str(vip_id)},
            )
            counts["error"] = counts.get("error", 0) + 1
            continue
        key = status or "unknown"
        counts[key] = counts.get(key, 0) + 1
        logger.info(
            "recontact_execute_result",
            extra={"vip_id": str(vip_id), "status": key},
        )
    return counts


class RecontactJob:
    """Periodically run due recontacts.

    ``start()`` is one-shot — once it returns (after ``stop()``), create a new
    instance to restart.
    """

    def __init__(
        self,
        service: RecontactService,
        *,
        interval_seconds: int = 3600,
    ) -> None:
        self._service = service
        self._interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the recontact loop until stop() is called."""
        logger.info(
            "recontact_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                counts = await asyncio.wait_for(
                    run_due_recontacts(self._service),
                    timeout=self._interval,
                )
                elapsed = time.monotonic() - t0
                logger.info(
                    "recontact_run_complete",
                    extra={
                        "counts": counts,
                        "duration_ms": int(elapsed * 1000),
                    },
                )
            except TimeoutError:
                logger.warning("recontact_run_timeout")
            except Exception:
                logger.exception("recontact_run_error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
                break
            except TimeoutError:
                continue

        logger.info("recontact_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on the next iteration."""
        self._stop_event.set()
        logger.debug("recontact_job_stop_signalled")


__all__ = ["RecontactJob", "run_due_recontacts"]
