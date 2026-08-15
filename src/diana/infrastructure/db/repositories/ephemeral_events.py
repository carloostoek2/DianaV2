"""EphemeralEventRepo — owner-injected time-bounded context (eventos temporales)."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import EphemeralEventRecord
from diana.infrastructure.db.models import EphemeralEvent

logger = logging.getLogger("diana.infrastructure.db")


def ephemeral_event_orm_to_record(row: EphemeralEvent) -> EphemeralEventRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return EphemeralEventRecord(
        id=row.id,
        body=row.body,
        start_at=row.start_at,
        end_at=row.end_at,
        is_paused=row.is_paused,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class EphemeralEventRepo:
    """Thin ephemeral-events persistence — no validation (service owns it)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        body: str,
        start_at: datetime,
        end_at: datetime,
        created_by: int | None = None,
    ) -> EphemeralEventRecord:
        async with self._sf() as session:
            row = EphemeralEvent(
                body=body,
                start_at=start_at,
                end_at=end_at,
                created_by=created_by,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return ephemeral_event_orm_to_record(row)

    async def get(self, event_id: UUID) -> EphemeralEventRecord | None:
        async with self._sf() as session:
            row = await session.get(EphemeralEvent, event_id)
            return ephemeral_event_orm_to_record(row) if row is not None else None

    async def list_all(self) -> list[EphemeralEventRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(EphemeralEvent).order_by(EphemeralEvent.start_at)
            )
            return [ephemeral_event_orm_to_record(row) for row in result.scalars()]

    async def update(
        self, event_id: UUID, *, body: str, start_at: datetime, end_at: datetime
    ) -> EphemeralEventRecord | None:
        async with self._sf() as session:
            row = await session.get(EphemeralEvent, event_id)
            if row is None:
                return None
            row.body = body
            row.start_at = start_at
            row.end_at = end_at
            await session.commit()
            await session.refresh(row)
            return ephemeral_event_orm_to_record(row)

    async def set_paused(self, event_id: UUID, paused: bool) -> EphemeralEventRecord | None:
        async with self._sf() as session:
            row = await session.get(EphemeralEvent, event_id)
            if row is None:
                return None
            row.is_paused = paused
            await session.commit()
            await session.refresh(row)
            return ephemeral_event_orm_to_record(row)

    async def terminate_now(self, event_id: UUID, now: datetime) -> EphemeralEventRecord | None:
        async with self._sf() as session:
            row = await session.get(EphemeralEvent, event_id)
            if row is None:
                return None
            row.end_at = now
            await session.commit()
            await session.refresh(row)
            return ephemeral_event_orm_to_record(row)

    async def delete(self, event_id: UUID) -> bool:
        async with self._sf() as session:
            row = await session.get(EphemeralEvent, event_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def find_active_at(self, now: datetime) -> list[EphemeralEventRecord]:
        """Events active at *now*: not paused and within ``[start_at, end_at)``."""
        async with self._sf() as session:
            result = await session.execute(
                select(EphemeralEvent).where(
                    EphemeralEvent.is_paused.is_(False),
                    EphemeralEvent.start_at <= now,
                    EphemeralEvent.end_at > now,
                )
            )
            return [ephemeral_event_orm_to_record(row) for row in result.scalars()]

    async def list_open(self, now: datetime) -> list[EphemeralEventRecord]:
        """Events not yet terminated at *now* (active + paused + future)."""
        async with self._sf() as session:
            result = await session.execute(
                select(EphemeralEvent)
                .where(EphemeralEvent.end_at > now)
                .order_by(EphemeralEvent.end_at)
            )
            return [ephemeral_event_orm_to_record(row) for row in result.scalars()]


__all__ = ["EphemeralEventRepo", "ephemeral_event_orm_to_record"]
