"""SqlOwnerMarkStore — durable owner feedback marks (false_positive, ...)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.owner_marks import FALSE_POSITIVE_KIND
from diana.infrastructure.db.models import OwnerMark

__all__ = ["SqlOwnerMarkStore"]


def week_window_utc(week_start: date, week_end: date) -> tuple[datetime, datetime]:
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)
    end = datetime(week_end.year, week_end.month, week_end.day, tzinfo=UTC)
    return start, end


class SqlOwnerMarkStore:
    """OwnerMarkStore against owner_marks (turn_id + kind unique)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def mark(
        self, turn_id: UUID, *, kind: str = FALSE_POSITIVE_KIND
    ) -> None:
        now = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                insert(OwnerMark)
                .values(turn_id=turn_id, kind=kind, created_at=now)
                .on_conflict_do_update(
                    index_elements=["turn_id", "kind"],
                    set_={"created_at": now},
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def count_in_range(
        self,
        week_start: date,
        week_end: date,
        *,
        kind: str = FALSE_POSITIVE_KIND,
    ) -> int:
        start, end = week_window_utc(week_start, week_end)
        async with self._sf() as session:
            result = await session.execute(
                select(func.count())
                .select_from(OwnerMark)
                .where(
                    and_(
                        OwnerMark.kind == kind,
                        OwnerMark.created_at >= start,
                        OwnerMark.created_at < end,
                    )
                )
            )
            return int(result.scalar_one() or 0)
