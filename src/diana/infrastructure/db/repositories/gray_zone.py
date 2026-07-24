"""GrayZoneQueryRepo — gray zone query lifecycle CRUD."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
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
    ) -> GrayZoneQuery:
        async with self._sf() as session:
            row = GrayZoneQuery(
                vip_id=vip_id,
                turn_id=turn_id,
                question=question,
                draft=draft,
                status="open",
                freeze_until=freeze_until,
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
        """Set query status and optionally resolved_at. Returns False if not found."""
        async with self._sf() as session:
            values: dict = {"status": status}
            if resolved_at is not None:
                values["resolved_at"] = resolved_at
            result = await session.execute(
                update(GrayZoneQuery)
                .where(GrayZoneQuery.id == query_id)
                .values(**values)
            )
            await session.commit()
            return result.rowcount > 0

    async def expire_older_than(self, timeout_hours: int) -> list[GrayZoneQuery]:
        """Mark open queries older than timeout_hours as expired. Returns expired rows."""
        async with self._sf() as session:
            cutoff = func.now() - text(f"interval '{timeout_hours} hours'")
            result = await session.execute(
                select(GrayZoneQuery).where(
                    GrayZoneQuery.status == "open",
                    GrayZoneQuery.created_at < cutoff,
                )
            )
            rows = list(result.scalars().all())
            for row in rows:
                row.status = "expired"
                row.resolved_at = func.now()
            await session.commit()
            return rows

    async def list_open(self) -> list[GrayZoneQuery]:
        async with self._sf() as session:
            result = await session.execute(
                select(GrayZoneQuery).where(GrayZoneQuery.status == "open")
            )
            return list(result.scalars().all())


__all__ = ["GrayZoneQueryRepo"]
