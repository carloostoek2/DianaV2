"""VipMoodStateRepo — 3-axis mood vector per VIP (Fase 3 writer, schema-only now)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import VipMoodStateRecord
from diana.infrastructure.db.models import VipMoodState


def vip_mood_state_orm_to_record(row: VipMoodState) -> VipMoodStateRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return VipMoodStateRecord(
        vip_id=row.vip_id,
        axis_playful_serious=row.axis_playful_serious,
        axis_warm_distant=row.axis_warm_distant,
        axis_energy=row.axis_energy,
        updated_at=row.updated_at,
    )


class SqlVipMoodStateRepo:
    """Thin mood persistence — no mood math here (Fase 3 computes elsewhere)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_by_vip(self, vip_id: Any) -> VipMoodStateRecord | None:
        async with self._sf() as session:
            row = await session.get(VipMoodState, vip_id)
            return vip_mood_state_orm_to_record(row) if row is not None else None

    async def upsert(self, record: VipMoodStateRecord) -> VipMoodStateRecord:
        stmt = (
            insert(VipMoodState)
            .values(
                vip_id=record.vip_id,
                axis_playful_serious=record.axis_playful_serious,
                axis_warm_distant=record.axis_warm_distant,
                axis_energy=record.axis_energy,
            )
            .on_conflict_do_update(
                index_elements=[VipMoodState.vip_id],
                set_={
                    "axis_playful_serious": record.axis_playful_serious,
                    "axis_warm_distant": record.axis_warm_distant,
                    "axis_energy": record.axis_energy,
                    "updated_at": func.now(),
                },
            )
            .returning(VipMoodState)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalar_one()
            return vip_mood_state_orm_to_record(row)


__all__ = ["SqlVipMoodStateRepo", "vip_mood_state_orm_to_record"]
