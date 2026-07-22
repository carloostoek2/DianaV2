"""In-process map of in-flight delivery tasks keyed by chat_id."""

from __future__ import annotations

import asyncio
from uuid import UUID


class TimerManager:
    """Track asyncio delivery tasks so cancel_pending can abort mid-flight."""

    def __init__(self) -> None:
        self._by_chat: dict[int, set[asyncio.Task]] = {}
        self._by_turn: dict[UUID, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, chat_id: int, turn_id: UUID, task: asyncio.Task
    ) -> None:
        async with self._lock:
            self._by_chat.setdefault(chat_id, set()).add(task)
            self._by_turn[turn_id] = task

            def _cleanup(t: asyncio.Task, *, cid: int = chat_id, tid: UUID = turn_id) -> None:
                bucket = self._by_chat.get(cid)
                if bucket is not None:
                    bucket.discard(t)
                    if not bucket:
                        self._by_chat.pop(cid, None)
                if self._by_turn.get(tid) is t:
                    self._by_turn.pop(tid, None)

            task.add_done_callback(_cleanup)

    async def cancel_chat(self, chat_id: int) -> int:
        async with self._lock:
            tasks = list(self._by_chat.get(chat_id, set()))
        cancelled = 0
        for task in tasks:
            if not task.done():
                task.cancel()
                cancelled += 1
        return cancelled
