"""GrayZoneQueryRepo — gray zone query lifecycle CRUD."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import GrayZoneQuery


class GrayZoneQueryRepo:
    """Gray zone query persistence.

    Supports insert (open), get_by_id, update_status, expire_older_than,
    and list_open.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(
        self,
        vip_id: UUID | None,
        turn_id: UUID,
        question: str,
        draft: str,
        freeze_until: datetime | None = None,
        chat_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> GrayZoneQuery:
        async with self._sf() as session:
            row = GrayZoneQuery(
                vip_id=vip_id,
                turn_id=turn_id,
                question=question,
                draft=draft,
                status="open",
                freeze_until=freeze_until,
                chat_id=chat_id,
                business_connection_id=business_connection_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_by_id(self, query_id: UUID) -> GrayZoneQuery | None:
        async with self._sf() as session:
            return await session.get(GrayZoneQuery, query_id)

    async def update_status(
        self,
        query_id: UUID,
        status: str,
        resolved_at: datetime | None = None,
    ) -> bool:
        """Set query status and optionally resolved_at. Returns False if not found.

        Re-opening a query (status ``open``) clears ``resolved_at`` so the row
        reads as a fresh open query again.
        """
        async with self._sf() as session:
            values: dict = {"status": status}
            if resolved_at is not None:
                values["resolved_at"] = resolved_at
            elif status == "open":
                values["resolved_at"] = None
            result = await session.execute(
                update(GrayZoneQuery)
                .where(GrayZoneQuery.id == query_id)
                .values(**values)
            )
            await session.commit()
            return result.rowcount > 0

    async def expire_older_than(self, timeout_hours: int) -> list[GrayZoneQuery]:
        """Atomically expire open queries older than timeout_hours; return expired rows.

        A single conditional UPDATE (``WHERE status = 'open'``) guards against
        the TOCTOU where a concurrent ``dx:`` resolution commits ``resolved``
        between a SELECT and the expiry write: only rows still open at
        statement time are expired.
        """
        async with self._sf() as session:
            # Compute cutoff in Python: PostgreSQL rejects bind params inside
            # INTERVAL literals (e.g. ``interval $1 hours`` → syntax error near $2).
            now = datetime.now(UTC)
            cutoff = now - timedelta(hours=int(timeout_hours))
            result = await session.execute(
                update(GrayZoneQuery)
                .where(
                    GrayZoneQuery.status == "open",
                    GrayZoneQuery.created_at < cutoff,
                )
                .values(status="expired", resolved_at=now)
                .returning(GrayZoneQuery)
            )
            rows = list(result.scalars().all())
            await session.commit()
            return rows

    async def get_open_by_turn_id(self, turn_id: UUID) -> GrayZoneQuery | None:
        """Return the open query for a given turn, or None."""
        async with self._sf() as session:
            result = await session.execute(
                select(GrayZoneQuery).where(
                    GrayZoneQuery.turn_id == turn_id,
                    GrayZoneQuery.status == "open",
                )
            )
            return result.scalar_one_or_none()

    async def get_open_by_vip_id(self, vip_id: UUID) -> GrayZoneQuery | None:
        """Return the most recent open query for a VIP, or None."""
        async with self._sf() as session:
            result = await session.execute(
                select(GrayZoneQuery)
                .where(
                    GrayZoneQuery.vip_id == vip_id,
                    GrayZoneQuery.status == "open",
                )
                .order_by(GrayZoneQuery.created_at.desc())
                .limit(1)
            )
            return result.scalars().first()

    async def get_open_by_chat_id(self, chat_id: int) -> GrayZoneQuery | None:
        """Return the most recent open query for a chat (atencion), or None.

        Used by the atencion freeze middleware: a non-VIP chat is "frozen"
        while it has an open gray zone query (A1 — freeze is the query row).
        """
        async with self._sf() as session:
            result = await session.execute(
                select(GrayZoneQuery)
                .where(
                    GrayZoneQuery.chat_id == chat_id,
                    GrayZoneQuery.status == "open",
                )
                .order_by(GrayZoneQuery.created_at.desc())
                .limit(1)
            )
            return result.scalars().first()

    async def list_open(self) -> list[GrayZoneQuery]:
        async with self._sf() as session:
            result = await session.execute(
                select(GrayZoneQuery).where(GrayZoneQuery.status == "open")
            )
            return list(result.scalars().all())


__all__ = ["GrayZoneQueryRepo"]
