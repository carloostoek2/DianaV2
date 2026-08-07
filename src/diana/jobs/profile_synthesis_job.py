"""ProfileSynthesisJob — periodic scan + drain + synthesize (application only).

Periodically wraps the two Fase 1 application services — the trigger
(``scan_inactivity`` → enqueue ``session_close``) and the synthesis service
(``synthesize`` each pending VIP). Contains NO business logic (AGENTS.md §2.1:
jobs delegate to Application Services; ``CalibrationJob`` is the pattern).

``run_profile_synthesis_cycle`` is the one-shot runner used by tests: scan,
drain every pending item, synthesize each (per-item try/except — a failure is
logged and treated as ``failed``, ``release`` runs in a ``finally`` so the VIP
is never stuck in-flight), and report. It never propagates out.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("diana.jobs")

__all__ = ["ProfileSynthesisJob", "run_profile_synthesis_cycle"]


async def run_profile_synthesis_cycle(
    trigger_service: Any, synthesis_service: Any
) -> dict[str, Any]:
    """One-shot: scan inactivity, drain pending, synthesize each. Never raises out."""
    scan = await trigger_service.scan_inactivity(datetime.now(UTC))
    pending = trigger_service.drain_pending()
    results: list[str] = []
    for vip_id, trigger in pending:
        try:
            report = await synthesis_service.synthesize(vip_id, trigger)
            results.append(report.status)
        except Exception:
            logger.exception(
                "profile_synthesis_item_failed",
                extra={"vip_id": str(vip_id), "trigger": trigger},
            )
            results.append("failed")
        finally:
            trigger_service.release(vip_id)

    logger.info(
        "profile_synthesis_cycle_complete",
        extra={
            "scanned": scan,
            "items": len(pending),
            "results": results,
        },
    )
    return {"scanned": scan, "items": len(pending), "results": results}


class ProfileSynthesisJob:
    """Periodically run the profile-synthesis cycle (scan + drain + synthesize).

    ``start()`` is one-shot — after ``stop()``, create a new instance to
    restart. Wraps application services only (AGENTS.md); no business logic.
    """

    def __init__(
        self,
        trigger_service: Any,
        synthesis_service: Any,
        *,
        interval_seconds: int = 900,
    ) -> None:
        self._trigger = trigger_service
        self._service = synthesis_service
        self._interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the synthesis cycle loop until stop() is called."""
        logger.info(
            "profile_synthesis_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    run_profile_synthesis_cycle(self._trigger, self._service),
                    timeout=self._interval,
                )
                elapsed = time.monotonic() - t0
                logger.info(
                    "profile_synthesis_job_tick",
                    extra={
                        "result": result,
                        "duration_ms": int(elapsed * 1000),
                    },
                )
            except TimeoutError:
                logger.warning("profile_synthesis_cycle_timeout")
            except Exception:
                logger.exception("profile_synthesis_cycle_error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
                break
            except TimeoutError:
                continue

        logger.info("profile_synthesis_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on the next iteration."""
        self._stop_event.set()
        logger.debug("profile_synthesis_job_stop_signalled")
