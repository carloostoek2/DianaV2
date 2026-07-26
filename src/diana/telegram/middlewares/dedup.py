"""DedupMiddleware — drop Telegram update redeliveries (process-local).

In-memory TTL cache keyed by update_id and/or callback.id.
Single-instance only; multi-replica deployments need a shared store (out of scope).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger("diana.telegram")

Key = tuple[str, Any]


class DedupMiddleware(BaseMiddleware):
    """Silent drop of duplicate updates within ``ttl_s``.

    Keys (when available):
    - ``("update_id", update.update_id)`` from ``data["event_update"]``
    - ``("callback_id", event.id)`` for CallbackQuery

    No weak composite keys (chat/message) — avoid false positives.
    """

    def __init__(
        self,
        *,
        ttl_s: float = 300.0,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_s = ttl_s
        self._time_fn = time_fn or time.monotonic
        self._seen: dict[Key, float] = {}

    def _prune(self, now: float) -> None:
        expired = [k for k, exp in self._seen.items() if exp <= now]
        for k in expired:
            del self._seen[k]

    def _collect_keys(self, event: TelegramObject, data: dict[str, Any]) -> list[Key]:
        keys: list[Key] = []
        update = data.get("event_update")
        if update is not None:
            update_id = getattr(update, "update_id", None)
            if update_id is not None:
                keys.append(("update_id", update_id))
        if isinstance(event, CallbackQuery):
            cq_id = getattr(event, "id", None)
            if cq_id:
                keys.append(("callback_id", cq_id))
        return keys

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        now = self._time_fn()
        self._prune(now)
        keys = self._collect_keys(event, data)
        if not keys:
            return await handler(event, data)

        if any(k in self._seen and self._seen[k] > now for k in keys):
            logger.info(
                "telegram_update_dedup",
                extra={
                    "keys": [list(k) for k in keys],
                    "event_type": type(event).__name__,
                },
            )
            return None

        expiry = now + self._ttl_s
        for k in keys:
            self._seen[k] = expiry
        return await handler(event, data)


__all__ = ["DedupMiddleware"]
