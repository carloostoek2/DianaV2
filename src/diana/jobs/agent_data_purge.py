"""AgentDataPurgeJob — periodic TTL purge of agent-evolution tables."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("diana.jobs")


class AgentDataPurgeJob:
    """Periodic TTL purge of agent-evolution tables (vip_profile_history,
    turn_category_log, emotional_signal_log). Delegates to each store's
    purge_expired(ttl_days); no business logic here (AGENTS.md).

    ``start()`` is one-shot — once it returns (after ``stop()`` is called),
    the instance cannot be restarted. A failure in ONE store does not stop
    the loop (each store is wrapped in its own try/except).
    """

    def __init__(
        self,
        stores: list[tuple[Any, int]],
        *,
        interval_seconds: int = 3600,
    ) -> None:
        self._stores = list(stores)
        self._interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        logger.info(
            "agent_data_purge_job_started",
            extra={"interval_seconds": self._interval, "stores": len(self._stores)},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            total_deleted = 0
            ttl_by_index: dict[int, int] = {}
            for index, (store, ttl) in enumerate(self._stores):
                try:
                    deleted = await asyncio.wait_for(
                        store.purge_expired(ttl),
                        timeout=self._interval,
                    )
                    deleted = int(deleted or 0)
                except TimeoutError:
                    logger.warning(
                        "agent_data_purge_store_timeout",
                        extra={"index": index, "ttl_days": ttl},
                    )
                    deleted = 0
                except Exception:
                    logger.exception(
                        "agent_data_purge_store_error",
                        extra={"index": index, "ttl_days": ttl},
                    )
                    deleted = 0
                total_deleted += deleted
                ttl_by_index[index] = ttl
            elapsed = time.monotonic() - t0
            if total_deleted:
                logger.info(
                    "agent_data_purge_run_complete",
                    extra={
                        "deleted": total_deleted,
                        "ttl_by_index": ttl_by_index,
                        "duration_ms": int(elapsed * 1000),
                    },
                )
            else:
                logger.debug(
                    "agent_data_purge_run_noop",
                    extra={"interval_seconds": self._interval},
                )

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
                break  # stop event was set during the timeout
            except TimeoutError:
                continue  # normal interval elapsed

        logger.info("agent_data_purge_job_stopped")

    async def stop(self) -> None:
        """Signal the loop to stop on the next iteration."""
        self._stop_event.set()
        logger.debug("agent_data_purge_job_stop_signalled")


__all__ = ["AgentDataPurgeJob"]
