"""SqlReimportCursorStore — durable rotation cursor for the history re-import.

Persists the last re-imported VIP's ``telegram_user_id`` in ``system_config``
(key ``history_reimport_cursor``) so the one-VIP-per-hour scheduler resumes
mid-cycle after a restart instead of repeating the first VIP. Pure persistence:
no business logic (AGENTS.md §2.1) — the rotation lives in
``application/history_reimport.py``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore

__all__ = ["SqlReimportCursorStore"]

_CURSOR_KEY = "history_reimport_cursor"


class SqlReimportCursorStore:
    """``ReimportCursorStore`` over the generic system_config table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._config = SqlSystemConfigStore(session_factory)

    async def get_cursor(self) -> int | None:
        value = await self._config.get(_CURSOR_KEY)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def set_cursor(self, telegram_user_id: int) -> None:
        await self._config.set(_CURSOR_KEY, int(telegram_user_id))
