"""CalibrationJob — dual-threshold calibration + drift cycle (application only)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from diana.application.calibration_service import CalibrationService

logger = logging.getLogger("diana.jobs")

__all__ = ["CalibrationJob", "run_calibration_cycle"]


async def run_calibration_cycle(service: CalibrationService) -> dict[str, Any]:
    """One-shot: calibrate_thresholds then detect_drift. Never raises out."""
    try:
        report = await service.calibrate_thresholds()
    except Exception:
        logger.exception("calibration_run_error")
        return {"calibration": "error", "drift": {}, "error": 1}

    status = getattr(report, "status", "unknown")
    out: dict[str, Any] = {"calibration": status, "drift": {}}

    try:
        drift = await service.detect_drift()
        out["drift"] = drift if isinstance(drift, dict) else {}
    except Exception:
        logger.exception("calibration_drift_error")
        out["error"] = 1
        out["drift"] = {}

    logger.info(
        "calibration_run_complete",
        extra={
            "calibration": out["calibration"],
            "drift": out["drift"],
        },
    )
    return out


class CalibrationJob:
    """Periodically run calibration + drift detection.

    ``start()`` is one-shot — after ``stop()``, create a new instance to restart.
    """

    def __init__(
        self,
        service: CalibrationService,
        *,
        interval_seconds: int = 3600,
    ) -> None:
        self._service = service
        self._interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the calibration loop until stop() is called."""
        logger.info(
            "calibration_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    run_calibration_cycle(self._service),
                    timeout=self._interval,
                )
                elapsed = time.monotonic() - t0
                logger.info(
                    "calibration_job_tick",
                    extra={
                        "result": result,
                        "duration_ms": int(elapsed * 1000),
                    },
                )
            except TimeoutError:
                logger.warning("calibration_run_timeout")
            except Exception:
                logger.exception("calibration_run_error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
                break
            except TimeoutError:
                continue

        logger.info("calibration_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on the next iteration."""
        self._stop_event.set()
        logger.debug("calibration_job_stop_signalled")
