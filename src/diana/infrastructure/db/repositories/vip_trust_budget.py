"""VipTrustBudgetRepo — trust score per (VIP, turn_category) (Fase 5, schema-only)."""

from __future__ import annotations

from datetime import datetime
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


def _clamp(value: float) -> float:
    """Clamp a trust score to [0, 1] (the record validates the range too)."""
    return min(1.0, max(0.0, float(value)))


class SqlVipTrustBudgetRepo:
    """Thin (VIP, turn_category) budget persistence — no trust math here.

    The delta methods (``increment_autonomous`` / ``decrement_correction``) are
    ATOMIC SQL updates: on an EXISTING row the score is computed server-side
    (``LEAST(1, GREATEST(0, score + delta))``), so concurrent deltas on the same
    key cannot lose each other. Caveat (review round 1): two concurrent
    FIRST-inserts of the same NEW key serialize on the unique index — the second
    blocks until the first commits, then takes the DO UPDATE branch, so the
    INSERT branch (client-side clamp of ``initial ± delta``) wins exactly once.
    """

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

    async def increment_autonomous(
        self,
        vip_id: Any,
        turn_category: str,
        *,
        delta: float,
        initial: float,
    ) -> VipTrustBudgetRecord:
        """Autonomous-without-correction event: atomic +small score bump.

        INSERT branch (first autonomous run) seeds ``clamp(initial + delta)``;
        the UPDATE branch bumps the existing score server-side with a SQL clamp.
        """
        stmt = (
            insert(VipTrustBudget)
            .values(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=_clamp(initial + delta),
                autonomous_count=1,
            )
            .on_conflict_do_update(
                index_elements=[VipTrustBudget.vip_id, VipTrustBudget.turn_category],
                set_={
                    "trust_score": func.least(
                        1.0,
                        func.greatest(0.0, VipTrustBudget.trust_score + delta),
                    ),
                    "autonomous_count": VipTrustBudget.autonomous_count + 1,
                    "updated_at": func.now(),
                },
            )
            .returning(VipTrustBudget)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return vip_trust_budget_orm_to_record(result.scalar_one())

    async def decrement_correction(
        self,
        vip_id: Any,
        turn_category: str,
        *,
        delta: float,
        initial: float,
        correction_time: datetime,
    ) -> VipTrustBudgetRecord:
        """Owner-correction event: atomic decay + counter + correction timestamp.

        INSERT branch seeds ``clamp(initial - delta)``; the UPDATE branch decays
        server-side with a SQL clamp and stamps ``last_correction_at``.
        """
        stmt = (
            insert(VipTrustBudget)
            .values(
                vip_id=vip_id,
                turn_category=turn_category,
                trust_score=_clamp(initial - delta),
                correction_count=1,
                last_correction_at=correction_time,
            )
            .on_conflict_do_update(
                index_elements=[VipTrustBudget.vip_id, VipTrustBudget.turn_category],
                set_={
                    "trust_score": func.least(
                        1.0,
                        func.greatest(0.0, VipTrustBudget.trust_score - delta),
                    ),
                    "correction_count": VipTrustBudget.correction_count + 1,
                    "last_correction_at": correction_time,
                    "updated_at": func.now(),
                },
            )
            .returning(VipTrustBudget)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return vip_trust_budget_orm_to_record(result.scalar_one())

    async def list_by_vip(self, vip_id: Any) -> list[VipTrustBudgetRecord]:
        """All (category, score) rows for a VIP, ordered by category (EA-06)."""
        async with self._sf() as session:
            result = await session.execute(
                select(VipTrustBudget)
                .where(VipTrustBudget.vip_id == vip_id)
                .order_by(VipTrustBudget.turn_category)
            )
            return [
                vip_trust_budget_orm_to_record(row) for row in result.scalars()
            ]


__all__ = ["SqlVipTrustBudgetRepo", "vip_trust_budget_orm_to_record"]
