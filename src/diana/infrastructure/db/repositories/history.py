"""SqlMessageHistoryRepo — append + get_recent (chronological)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy import delete, func, select, tuple_
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

    async def append_missing(
        self,
        chat_id: int,
        *,
        rows: Sequence[tuple[str, str, int | None, datetime | None]],
    ) -> int:
        """Idempotent seed insert: append only rows not already stored.

        Rows are ``(role, text, telegram_message_id, timestamp)``. A row whose
        ``telegram_message_id`` already exists for the chat is skipped; rows
        without an id are matched by ``(timestamp, text)``. Returns the number
        of appended rows. One transaction: a partial failure leaves nothing.
        """
        now = datetime.now(UTC)
        normalized = [
            (role, text, mid, (ts or now).astimezone(UTC) if ts is not None else now)
            for role, text, mid, ts in rows
        ]
        async with self._sf() as session:
            result = await session.execute(
                select(MessageHistory.telegram_message_id).where(
                    MessageHistory.chat_id == chat_id,
                    MessageHistory.telegram_message_id.is_not(None),
                )
            )
            existing_ids = {row[0] for row in result.all() if row[0] is not None}
            result = await session.execute(
                select(MessageHistory.timestamp, MessageHistory.text).where(
                    MessageHistory.chat_id == chat_id,
                    MessageHistory.telegram_message_id.is_(None),
                )
            )
            existing_no_id = {
                (ts.astimezone(UTC) if ts is not None else None, text)
                for ts, text in result.all()
            }
            added = 0
            for role, text, mid, ts in normalized:
                if mid is not None:
                    if mid in existing_ids:
                        continue
                    existing_ids.add(mid)
                else:
                    key = (ts.astimezone(UTC) if ts is not None else None, text)
                    if key in existing_no_id:
                        continue
                    existing_no_id.add(key)
                session.add(
                    MessageHistory(
                        chat_id=chat_id,
                        telegram_message_id=mid,
                        role=role,
                        text=text,
                        timestamp=ts,
                    )
                )
                added += 1
            await session.commit()
            return added

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

    async def list_all(
        self,
        chat_id: int,
        *,
        page_size: int = 500,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Read chat history chronological (oldest first).

        Paginated in ``page_size`` chunks for backfill of long histories
        (F5-08); same dict shape as ``rows_to_recent_messages``
        (role/text/telegram_message_id/timestamp). With ``since`` only rows
        at/after that instant are returned. With ``limit`` the read is
        BOUNDED — the post-turn extraction must never materialize a whole
        chat: only the newest ``limit`` matching rows are fetched in one DESC
        query (skips the O(total) keyset walk).

        Fix round (M3): keyset pagination on ``(timestamp, id)`` instead of
        OFFSET — if the chat receives messages while the backfill runs, no
        page shifts under the cursor, so rows are neither skipped nor
        duplicated across pages.
        """
        if limit is not None:
            if limit <= 0:
                return []
            async with self._sf() as session:
                query = (
                    select(MessageHistory)
                    .where(MessageHistory.chat_id == chat_id)
                    .order_by(
                        MessageHistory.timestamp.desc(),
                        MessageHistory.id.desc(),
                    )
                    .limit(limit)
                )
                if since is not None:
                    query = query.where(MessageHistory.timestamp >= since)
                result = await session.execute(query)
                rows = list(result.scalars().all())
                return rows_to_recent_messages(rows, limit=limit)

        out: list[dict] = []
        last_ts: datetime | None = None
        last_id: int | None = None
        while True:
            async with self._sf() as session:
                query = (
                    select(MessageHistory)
                    .where(MessageHistory.chat_id == chat_id)
                    .order_by(MessageHistory.timestamp.asc(), MessageHistory.id.asc())
                    .limit(page_size)
                )
                if since is not None:
                    query = query.where(MessageHistory.timestamp >= since)
                if last_ts is not None:
                    query = query.where(
                        tuple_(MessageHistory.timestamp, MessageHistory.id)
                        > (last_ts, last_id)
                    )
                result = await session.execute(query)
                rows = list(result.scalars().all())
            if not rows:
                break
            for row in rows:
                ts = row.timestamp
                out.append(
                    {
                        "role": row.role,
                        "text": row.text,
                        "telegram_message_id": row.telegram_message_id,
                        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    }
                )
            last_ts = rows[-1].timestamp
            last_id = rows[-1].id
            if len(rows) < page_size:
                break
        return out

    async def count(self, chat_id: int) -> int:
        """Row count of one chat's history (F5 Pool 2 fix round L6/F7).

        Cheap ``count(*)`` for the queue's step estimator — the caller never
        materializes the full history just to compute the DM's "~N pasos".
        """
        async with self._sf() as session:
            result = await session.execute(
                select(func.count())
                .select_from(MessageHistory)
                .where(MessageHistory.chat_id == chat_id)
            )
            return int(result.scalar_one() or 0)


__all__ = ["SqlMessageHistoryRepo", "rows_to_recent_messages"]
