"""EmbeddingWarmupJob — background embedding-model warmup at boot.

hardener/persona-reglas ítem 3 (D1). Started from ``main.py`` as a non-awaited
``asyncio.create_task`` right after ``build_app``, so ``start_polling`` never
waits for the ~12 s model load (which itself runs in a worker thread inside
``EmbeddingService``). A failed warmup is logged and the bot keeps working:
the lazy load inside ``embed()`` is still available.

After the warmup the job keeps an optional periodic repair pass (wired in D2).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("diana.jobs")

DEFAULT_REPAIR_INTERVAL_SECONDS = 1800.0


class EmbeddingWarmupJob:
    """Warm up the embedder once, then run the (optional) repair loop."""

    def __init__(
        self,
        embedder: Any,
        *,
        repair: Any | None = None,
        interval_seconds: float = DEFAULT_REPAIR_INTERVAL_SECONDS,
        repair_limit: int = 50,
    ) -> None:
        self._embedder = embedder
        self._repair = repair
        self._interval = float(interval_seconds)
        self._repair_limit = int(repair_limit)
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        try:
            await self._embedder.warmup()
            logger.info(
                "embedding_warmup_done",
                extra={"model_name": getattr(self._embedder, "model_name", None)},
            )
        except Exception:
            # The lazy load inside embed() stays available.
            logger.exception("embedding_warmup_failed")
        while not self._stop_event.is_set():
            await self._repair_pass()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    async def _repair_pass(self) -> None:
        if self._repair is None:
            return

    def stop(self) -> None:
        self._stop_event.set()


__all__ = ["DEFAULT_REPAIR_INTERVAL_SECONDS", "EmbeddingWarmupJob"]
