"""VipProfileHistoryRepo — snapshots of synthesized profile versions (drift audit)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import VipProfileHistoryRecord
from diana.infrastructure.db.models import VipProfileHistory


def vip_profile_history_orm_to_record(
    row: VipProfileHistory,
) -> VipProfileHistoryRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return VipProfileHistoryRecord(
        id=row.id,
        vip_id=row.vip_id,
        version=row.version,
        profile_snapshot=dict(row.profile_snapshot),
        diff_summary=row.diff_summary,
        created_at=row.created_at,
    )


class SqlVipProfileHistoryRepo:
    """Thin append-only snapshot store — no drift/comparison logic.

    ``purge_expired`` mirrors ``SqlTraceStore.purge_expired`` (batched
    ``DELETE ... WHERE id IN (SELECT id ... LIMIT 1000)``).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(self, record: VipProfileHistoryRecord) -> VipProfileHistoryRecord:
        async with self._sf() as session:
            row = VipProfileHistory(
                id=record.id,
                vip_id=record.vip_id,
                version=record.version,
                profile_snapshot=record.profile_snapshot,
                diff_summary=record.diff_summary,
                created_at=record.created_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return vip_profile_history_orm_to_record(row)

    async def list_by_vip(self, vip_id: UUID) -> list[VipProfileHistoryRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(VipProfileHistory)
                .where(VipProfileHistory.vip_id == vip_id)
                .order_by(VipProfileHistory.version.desc())
            )
            return [vip_profile_history_orm_to_record(r) for r in result.scalars()]

    async def purge_expired(self, ttl_days: int) -> int:
        batch_size = 1000
        cutoff = func.now() - text(":ttl_days * INTERVAL '1 day'")
        total_deleted = 0

        while True:
            async with self._sf() as session:
                batch_ids = (
                    select(VipProfileHistory.id)
                    .where(VipProfileHistory.created_at < cutoff)
                    .limit(batch_size)
                )
                stmt = delete(VipProfileHistory).where(
                    VipProfileHistory.id.in_(batch_ids)
                )
                result = await session.execute(stmt, {"ttl_days": ttl_days})
                await session.commit()
                batch_count = (
                    result.rowcount if result.rowcount and result.rowcount > 0 else 0
                )
                total_deleted += batch_count
                if batch_count < batch_size:
                    break

        return total_deleted


__all__ = ["SqlVipProfileHistoryRepo", "vip_profile_history_orm_to_record"]
