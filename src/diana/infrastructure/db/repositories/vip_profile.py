"""VipProfileRepo — LLM-synthesized per-VIP profile (Fase 1 writer, schema-only now)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import VipProfileRecord
from diana.infrastructure.db.models import VipProfile


def vip_profile_orm_to_record(row: VipProfile) -> VipProfileRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return VipProfileRecord(
        vip_id=row.vip_id,
        stable_traits=dict(row.stable_traits),
        recent_trend=dict(row.recent_trend),
        sensitivities=list(row.sensitivities),
        version=row.version,
        last_synthesized_at=row.last_synthesized_at,
        synthesis_trigger=row.synthesis_trigger,
    )


class SqlVipProfileRepo:
    """Thin persistence for the synthesized profile — no synthesis logic.

    ``insert`` is a simple upsert keyed on ``vip_id`` (Postgres ON CONFLICT):
    it overwrites the mutable columns with the caller's record values verbatim.
    Versioning (incrementing ``version`` and snapshotting the prior profile
    into ``vip_profile_history``) is the Fase 1 service's job — this repo
    never bumps the version itself.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_by_vip(self, vip_id: Any) -> VipProfileRecord | None:
        async with self._sf() as session:
            row = await session.get(VipProfile, vip_id)
            return vip_profile_orm_to_record(row) if row is not None else None

    async def insert(self, record: VipProfileRecord) -> VipProfileRecord:
        stmt = (
            insert(VipProfile)
            .values(
                vip_id=record.vip_id,
                stable_traits=record.stable_traits,
                recent_trend=record.recent_trend,
                sensitivities=record.sensitivities,
                version=record.version,
                last_synthesized_at=record.last_synthesized_at,
                synthesis_trigger=record.synthesis_trigger,
            )
            .on_conflict_do_update(
                index_elements=[VipProfile.vip_id],
                set_={
                    "stable_traits": record.stable_traits,
                    "recent_trend": record.recent_trend,
                    "sensitivities": record.sensitivities,
                    "version": record.version,
                    "last_synthesized_at": record.last_synthesized_at,
                    "synthesis_trigger": record.synthesis_trigger,
                },
            )
            .returning(VipProfile)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalar_one()
            return vip_profile_orm_to_record(row)


__all__ = ["SqlVipProfileRepo", "vip_profile_orm_to_record"]
