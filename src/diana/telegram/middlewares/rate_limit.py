"""RateLimitMiddleware — per-user sliding window throttle (process-local).

Owner is exempt via constructor ``owner_telegram_id`` (runs before OwnerDetection).
Single-instance only; multi-replica needs a shared store (out of scope).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger("diana.telegram")


class RateLimitMiddleware(BaseMiddleware):
    """Throttle noisy non-owner users; never raise on drop.

    Messages: silent drop + log. Callbacks: answer ``Slow down`` with show_alert.
    """

    def __init__(
        self,
        *,
        max_events: int = 20,
        window_s: float = 10.0,
        owner_telegram_id: int | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._max_events = max_events
        self._window_s = window_s
        self._owner_telegram_id = owner_telegram_id
        self._time_fn = time_fn or time.monotonic
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def _user_key(self, event: TelegramObject) -> int | None:
        from_user = getattr(event, "from_user", None)
        if from_user is not None:
            uid = getattr(from_user, "id", None)
            if uid is not None:
                return int(uid)
        chat = getattr(event, "chat", None)
        if chat is not None:
            cid = getattr(chat, "id", None)
            if cid is not None:
                return int(cid)
        msg = getattr(event, "message", None)
        if msg is not None:
            chat = getattr(msg, "chat", None)
            if chat is not None:
                cid = getattr(chat, "id", None)
                if cid is not None:
                    return int(cid)
        return None

    def _prune_window(self, q: deque[float], now: float) -> None:
        cutoff = now - self._window_s
        while q and q[0] <= cutoff:
            q.popleft()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = self._user_key(event)
        if user_id is None:
            return await handler(event, data)

        if (
            self._owner_telegram_id is not None
            and user_id == self._owner_telegram_id
        ):
            return await handler(event, data)

        now = self._time_fn()
        q = self._events[user_id]
        self._prune_window(q, now)

        if len(q) >= self._max_events:
            logger.info(
                "telegram_rate_limited",
                extra={
                    "user_id": user_id,
                    "count": len(q),
                    "window_s": self._window_s,
                    "max_events": self._max_events,
                },
            )
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("Slow down", show_alert=True)
                except Exception:
                    logger.exception("telegram_rate_limit_answer_failed")
            return None

        q.append(now)
        return await handler(event, data)


__all__ = ["RateLimitMiddleware"]
