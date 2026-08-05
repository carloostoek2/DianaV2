"""SqlDailyMessageLimitStore — atomic per-chat daily client-message counter.

F4-02 (atencion channel): increments the ``daily_message_limits`` row for
``(chat_id, fecha_local)`` in a single ``INSERT ... ON CONFLICT ... DO UPDATE
... RETURNING count`` statement (REQ-ATN-04 determinism — no read/write drift).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import DailyMessageLimit

__all__ = ["SqlDailyMessageLimitStore"]


class SqlDailyMessageLimitStore:
    """DailyMessageLimitStore against ``daily_message_limits`` (chat_id, fecha_local)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def increment(self, chat_id: int, *, fecha_local: date) -> int:
        stmt = (
            insert(DailyMessageLimit)
            .values(chat_id=chat_id, fecha_local=fecha_local, count=1)
            .on_conflict_do_update(
                index_elements=["chat_id", "fecha_local"],
                set_={"count": DailyMessageLimit.count + 1},
            )
            .returning(DailyMessageLimit.count)
        )
        async with self._sf() as session:
            count = (await session.execute(stmt)).scalar_one()
            await session.commit()
            return count
