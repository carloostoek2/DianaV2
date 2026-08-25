"""SqlProfileSynthesisQueueRepo — durable synthesis queue (Fila 4 C4).

One row per VIP (PK), lifecycle ``pending → processing`` (then deleted on
release). Atomic claim (CAS) so the job's drain never double-processes;
``recover_stale`` resets abandoned ``processing`` rows back to ``pending``
(pattern ``backfill_queue.recover_stale``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import ProfileSynthesisQueueRecord
from diana.infrastructure.db.models import ProfileSynthesisQueue

__all__ = ["SqlProfileSynthesisQueueRepo"]


def profile_synthesis_queue_orm_to_record(
    row: ProfileSynthesisQueue,
) -> ProfileSynthesisQueueRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return ProfileSynthesisQueueRecord(
        vip_id=row.vip_id,
        trigger=row.trigger,
        status=row.status,
        attempts=row.attempts,
        enqueued_at=row.enqueued_at,
        started_at=row.started_at,
        updated_at=row.updated_at,
    )


class SqlProfileSynthesisQueueRepo:
    """Thin durable queue — no trigger/synthesis logic here."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def upsert_pending(
        self, vip_id: UUID, trigger: str
    ) -> ProfileSynthesisQueueRecord:
        """Pending upsert: a re-enqueue refreshes the trigger, never the status.

        INSERT branch seeds ``pending``; the UPDATE branch only refreshes the
        trigger + timestamp when the row exists (a ``processing`` row stays
        ``processing`` — the in-memory guard already dedups within the
        process, so this is a crash-safety backstop).
        """
        stmt = (
            insert(ProfileSynthesisQueue)
            .values(vip_id=vip_id, trigger=trigger)
            .on_conflict_do_update(
                index_elements=[ProfileSynthesisQueue.vip_id],
                set_={
                    "trigger": trigger,
                    "updated_at": func.now(),
                },
            )
            .returning(ProfileSynthesisQueue)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return profile_synthesis_queue_orm_to_record(result.scalar_one())

    async def drain(self, limit: int = 100) -> list[ProfileSynthesisQueueRecord]:
        """Claim pending rows atomically: pending → processing (CAS).

        Only rows still ``pending`` at UPDATE time are claimed; a concurrent
        drain cannot double-claim. Returns the claimed rows (any order).
        """
        claimed_subq = (
            select(ProfileSynthesisQueue.vip_id)
            .where(ProfileSynthesisQueue.status == "pending")
            .limit(int(limit))
        )
        stmt = (
            update(ProfileSynthesisQueue)
            .where(
                ProfileSynthesisQueue.vip_id.in_(claimed_subq),
                ProfileSynthesisQueue.status == "pending",
            )
            .values(
                status="processing",
                started_at=datetime.now(UTC),
                updated_at=func.now(),
            )
            .returning(ProfileSynthesisQueue)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return [
                profile_synthesis_queue_orm_to_record(row)
                for row in result.scalars().all()
            ]

    async def complete(self, vip_id: UUID) -> bool:
        """Remove the row after synthesis (success or permanent failure)."""
        stmt = ProfileSynthesisQueue.__table__.delete().where(
            ProfileSynthesisQueue.vip_id == vip_id
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return (result.rowcount or 0) > 0

    async def recover_stale(
        self, *, max_age_seconds: int = 3600
    ) -> int:
        """Reset abandoned ``processing`` rows back to ``pending``.

        A ``processing`` row untouched for ``max_age_seconds`` is presumed
        orphaned (crash mid-synthesis). Resetting lets the next scan re-enqueue
        without double-processing live runs.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=max(1, int(max_age_seconds)))
        stmt = (
            update(ProfileSynthesisQueue)
            .where(
                ProfileSynthesisQueue.status == "processing",
                ProfileSynthesisQueue.updated_at < cutoff,
            )
            .values(status="pending", started_at=None, updated_at=func.now())
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def list_pending(self, limit: int = 100) -> list[ProfileSynthesisQueueRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(ProfileSynthesisQueue)
                .where(ProfileSynthesisQueue.status == "pending")
                .limit(int(limit))
            )
            return [
                profile_synthesis_queue_orm_to_record(row) for row in result.scalars()
            ]
