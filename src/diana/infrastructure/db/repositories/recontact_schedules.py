"""RecontactScheduleRepo — thin CRUD for recontact_schedules."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import RecontactScheduleRecord
from diana.infrastructure.db.models import RecontactSchedule


def recontact_schedule_orm_to_record(row: RecontactSchedule) -> RecontactScheduleRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return RecontactScheduleRecord(
        id=row.id,
        vip_id=row.vip_id,
        last_contact_at=row.last_contact_at,
        next_contact_at=row.next_contact_at,
        status=row.status,
    )


class RecontactScheduleRepo:
    """Thin schedule persistence — no eligibility / is_blocked / feature flags."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def upsert_pending(
        self,
        vip_id: UUID,
        last_contact_at: datetime,
        next_contact_at: datetime | None,
    ) -> RecontactScheduleRecord:
        """Update pending row for vip_id or insert a new pending schedule."""
        async with self._sf() as session:
            result = await session.execute(
                select(RecontactSchedule).where(
                    RecontactSchedule.vip_id == vip_id,
                    RecontactSchedule.status == "pending",
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                row.last_contact_at = last_contact_at
                row.next_contact_at = next_contact_at
            else:
                row = RecontactSchedule(
                    vip_id=vip_id,
                    last_contact_at=last_contact_at,
                    next_contact_at=next_contact_at,
                    status="pending",
                )
                session.add(row)
            await session.commit()
            await session.refresh(row)
            return recontact_schedule_orm_to_record(row)

    async def get_pending_by_vip(
        self, vip_id: UUID
    ) -> RecontactScheduleRecord | None:
        async with self._sf() as session:
            result = await session.execute(
                select(RecontactSchedule).where(
                    RecontactSchedule.vip_id == vip_id,
                    RecontactSchedule.status == "pending",
                )
            )
            row = result.scalar_one_or_none()
            return recontact_schedule_orm_to_record(row) if row else None

    async def list_due(self, now: datetime) -> list[RecontactScheduleRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(RecontactSchedule).where(
                    RecontactSchedule.status == "pending",
                    RecontactSchedule.next_contact_at.is_not(None),
                    RecontactSchedule.next_contact_at <= now,
                )
            )
            return [
                recontact_schedule_orm_to_record(r) for r in result.scalars().all()
            ]

    async def cancel_pending(self, vip_id: UUID) -> bool:
        """pending → cancelled. Returns False if no pending row for vip."""
        async with self._sf() as session:
            result = await session.execute(
                update(RecontactSchedule)
                .where(
                    RecontactSchedule.vip_id == vip_id,
                    RecontactSchedule.status == "pending",
                )
                .values(status="cancelled")
            )
            await session.commit()
            return bool(result.rowcount and result.rowcount > 0)

    async def mark_done(self, schedule_id: UUID) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                update(RecontactSchedule)
                .where(RecontactSchedule.id == schedule_id)
                .values(status="done")
            )
            await session.commit()
            return bool(result.rowcount and result.rowcount > 0)


__all__ = ["RecontactScheduleRepo", "recontact_schedule_orm_to_record"]
