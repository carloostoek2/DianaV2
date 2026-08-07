"""VipTrustBudgetRepo — trust score per (VIP, turn_category) (Fase 5, schema-only)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import VipTrustBudgetRecord
from diana.infrastructure.db.models import VipTrustBudget


def vip_trust_budget_orm_to_record(row: VipTrustBudget) -> VipTrustBudgetRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return VipTrustBudgetRecord(
        vip_id=row.vip_id,
        turn_category=row.turn_category,
        trust_score=row.trust_score,
        correction_count=row.correction_count,
        autonomous_count=row.autonomous_count,
        last_correction_at=row.last_correction_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlVipTrustBudgetRepo:
    """Thin (VIP, turn_category) budget persistence — no trust math here."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_by_vip_and_category(
        self, vip_id: Any, turn_category: str
    ) -> VipTrustBudgetRecord | None:
        async with self._sf() as session:
            result = await session.execute(
                select(VipTrustBudget).where(
                    VipTrustBudget.vip_id == vip_id,
                    VipTrustBudget.turn_category == turn_category,
                )
            )
            row = result.scalar_one_or_none()
            return (
                vip_trust_budget_orm_to_record(row) if row is not None else None
            )

    async def upsert(self, record: VipTrustBudgetRecord) -> VipTrustBudgetRecord:
        stmt = (
            insert(VipTrustBudget)
            .values(
                vip_id=record.vip_id,
                turn_category=record.turn_category,
                trust_score=record.trust_score,
                correction_count=record.correction_count,
                autonomous_count=record.autonomous_count,
                last_correction_at=record.last_correction_at,
            )
            .on_conflict_do_update(
                index_elements=[VipTrustBudget.vip_id, VipTrustBudget.turn_category],
                set_={
                    "trust_score": record.trust_score,
                    "correction_count": record.correction_count,
                    "autonomous_count": record.autonomous_count,
                    "last_correction_at": record.last_correction_at,
                    "updated_at": func.now(),
                },
            )
            .returning(VipTrustBudget)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalar_one()
            return vip_trust_budget_orm_to_record(row)


__all__ = ["SqlVipTrustBudgetRepo", "vip_trust_budget_orm_to_record"]
