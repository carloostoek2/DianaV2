"""SqlMessageHistoryRepo — append + get_recent (chronological)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import MessageHistory


def rows_to_recent_messages(
    rows_desc: list[MessageHistory], *, limit: int
) -> list[dict]:
    """Convert DESC-ordered rows into chronological list[dict] (oldest first).

    Matches cognitive HistoryRetriever expectations: last N then chronological.
    """
    if limit <= 0:
        return []
    sliced = list(rows_desc[:limit])
    sliced.reverse()
    out: list[dict] = []
    for row in sliced:
        ts = row.timestamp
        out.append(
            {
                "role": row.role,
                "text": row.text,
                "telegram_message_id": row.telegram_message_id,
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            }
        )
    return out


class SqlMessageHistoryRepo:
    """Implements MessageHistoryWriter + MessageHistoryPort."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def append(
        self,
        chat_id: int,
        *,
        role: str,
        text: str,
        telegram_message_id: int | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        async with self._sf() as session:
            session.add(
                MessageHistory(
                    chat_id=chat_id,
                    telegram_message_id=telegram_message_id,
                    role=role,
                    text=text,
                    timestamp=timestamp or datetime.now(UTC),
                )
            )
            await session.commit()

    async def upsert_vip_message(
        self,
        chat_id: int,
        *,
        text: str,
        telegram_message_id: int | None,
        timestamp: datetime | None = None,
    ) -> str:
        """Update VIP text for an existing telegram_message_id, else insert."""
        ts = timestamp or datetime.now(UTC)
        if telegram_message_id is None:
            await self.append(
                chat_id,
                role="vip",
                text=text,
                telegram_message_id=None,
                timestamp=ts,
            )
            return "inserted"
        async with self._sf() as session:
            result = await session.execute(
                select(MessageHistory)
                .where(MessageHistory.chat_id == chat_id)
                .where(MessageHistory.role == "vip")
                .where(MessageHistory.telegram_message_id == telegram_message_id)
                .order_by(MessageHistory.id.asc())
            )
            rows = list(result.scalars().all())
            if not rows:
                session.add(
                    MessageHistory(
                        chat_id=chat_id,
                        telegram_message_id=telegram_message_id,
                        role="vip",
                        text=text,
                        timestamp=ts,
                    )
                )
                await session.commit()
                return "inserted"
            keep = rows[0]
            keep.text = text
            keep.timestamp = ts
            if len(rows) > 1:
                extra_ids = [r.id for r in rows[1:]]
                await session.execute(
                    delete(MessageHistory).where(MessageHistory.id.in_(extra_ids))
                )
            await session.commit()
            return "updated"

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]:
        if limit <= 0:
            return []
        async with self._sf() as session:
            result = await session.execute(
                select(MessageHistory)
                .where(MessageHistory.chat_id == chat_id)
                .order_by(MessageHistory.timestamp.desc())
                .limit(limit)
            )
            rows = list(result.scalars().all())
            return rows_to_recent_messages(rows, limit=limit)


__all__ = ["SqlMessageHistoryRepo", "rows_to_recent_messages"]
