"""GrayZoneExpirationJob — periodic expiration of stale doctrinal queries."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from diana.application.admin_service import AdminService
from diana.application.ports import GrayZoneServicePort, OwnerNotifierPort
from diana.application.turn_coordinator import (
    ChatLockTimeoutError,
    TurnCoordinator,
)

logger = logging.getLogger("diana.jobs")


class GrayZoneExpirationJob:
    """Periodically expire stale queries and escalate (or deliver) their turns.

    With ``admin`` injected, an expired query that still has a non-empty
    draft is converted into a supervised PendingApproval (via
    ``AdminService.create_supervised_delivery_from_gray_zone``) instead of
    being silently escalated. If the supervised delivery cannot be created
    (missing ``business_connection_id``, missing turn, terminal turn, or an
    unexpected error), the job falls back to the legacy ``escalated``
    transition so no turn is ever left stuck in ``gray_zone``. Queries
    without a draft, or with ``admin=None`` (flag OFF), keep the legacy
    ``escalated`` behavior byte-identical.

    ``start()`` is one-shot — once it returns (after ``stop()`` is called),
    the instance cannot be restarted. Create a new instance if needed.
    """

    def __init__(
        self,
        gray_zone: GrayZoneServicePort,
        coordinator: TurnCoordinator,
        notifier: OwnerNotifierPort,
        *,
        admin: AdminService | None = None,
        interval_seconds: int = 300,
    ) -> None:
        self._gray_zone = gray_zone
        self._coordinator = coordinator
        self._notifier = notifier
        self._admin = admin
        self._interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the expiration loop until stop() is called.

        One-shot: calling start() after stop() will return immediately
        since the stop event is already set.
        """
        logger.info(
            "expiration_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                expired = await asyncio.wait_for(
                    self._gray_zone.expire_old_queries(),
                    timeout=self._interval,
                )
                if expired:
                    delivery_count = 0
                    escalated_count = 0
                    failed_count = 0
                    for row in expired:
                        turn_id: UUID = (
                            row.turn_id
                            if isinstance(row.turn_id, UUID)
                            else UUID(str(row.turn_id))
                        )
                        draft = getattr(row, "draft", "") or ""
                        if draft.strip() and self._admin is not None:
                            try:
                                created = await self._admin.create_supervised_delivery_from_gray_zone(
                                    turn_id, row
                                )
                            except ChatLockTimeoutError:
                                # Lock contention with the dx: path or an owner
                                # callback: the other holder may be creating an
                                # approval for this very turn. Escalating would
                                # terminalize it mid-flight — count as failed.
                                # The row is already marked expired, so reopen
                                # it: otherwise the turn stays stranded (the
                                # next sweep only revisits open rows).
                                logger.warning(
                                    "expiration_delivery_lock_timeout",
                                    extra={"turn_id": str(turn_id)},
                                )
                                failed_count += 1
                                try:
                                    await self._gray_zone.reopen_query(row.id)
                                except Exception:
                                    logger.exception(
                                        "expiration_lock_timeout_reopen_error",
                                        extra={"turn_id": str(turn_id)},
                                    )
                                continue
                            except Exception:
                                logger.exception(
                                    "expiration_delivery_error",
                                    extra={"turn_id": str(turn_id)},
                                )
                                created = False
                            if created:
                                delivery_count += 1
                                continue
                            logger.warning(
                                "expiration_delivery_fallback_escalate",
                                extra={"turn_id": str(turn_id)},
                            )
                        try:
                            await self._coordinator.transition(
                                turn_id, "escalated"
                            )
                            escalated_count += 1
                        except Exception:
                            logger.exception(
                                "expiration_escalate_error",
                                extra={"turn_id": str(turn_id)},
                            )
                            failed_count += 1
                            # Double failure (delivery + escalate): reopen the
                            # query so a later run retries instead of stranding
                            # the turn in gray_zone with an expired query. Only
                            # when a supervised delivery was actually attempted
                            # — the admin=None (flag OFF) path keeps the legacy
                            # escalate-only failure behavior.
                            if draft.strip() and self._admin is not None:
                                try:
                                    await self._gray_zone.reopen_query(row.id)
                                except Exception:
                                    logger.exception(
                                        "expiration_reopen_error",
                                        extra={
                                            "turn_id": str(turn_id),
                                            "query_id": str(getattr(row, "id", None)),
                                        },
                                    )

                    try:
                        parts = [
                            f"{delivery_count} pending approval",
                            f"{escalated_count} escalated",
                        ]
                        if failed_count:
                            parts.append(f"{failed_count} failed")
                        await self._notifier.notify_info(
                            f"Gray zone queries expired: "
                            f"{', '.join(parts)} ({len(expired)} total)."
                        )
                    except Exception:
                        logger.exception("expiration_notify_error")

                    elapsed = time.monotonic() - t0
                    logger.info(
                        "expiration_run_complete",
                        extra={
                            "expired_count": len(expired),
                            "duration_ms": int(elapsed * 1000),
                        },
                    )
                else:
                    logger.debug(
                        "expiration_run_noop",
                        extra={"interval_seconds": self._interval},
                    )
            except TimeoutError:
                logger.warning("expiration_run_timeout")
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
