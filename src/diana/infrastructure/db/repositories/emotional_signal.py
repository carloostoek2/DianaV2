"""EmotionalSignalLogRepo — emotional signal per turn (detector writer)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import EmotionalSignalRecord
from diana.infrastructure.db.models import EmotionalSignalLog


def emotional_signal_log_orm_to_record(
    row: EmotionalSignalLog,
) -> EmotionalSignalRecord:
    """Pure mapper ORM → record (unit-testable without DB).

    Note: the DB row is written only when a signal is detected, so this mapper
    always returns ``signal_detected=True``.
    """
    return EmotionalSignalRecord(
        signal_detected=True,
        signal_type=row.signal_type,
        intensity=row.intensity,
        should_trigger_synthesis=row.should_trigger_synthesis,
        should_escalate_to_owner=row.should_escalate_to_owner,
        pipeline_would_have_escalated=row.pipeline_would_have_escalated,
    )


class SqlEmotionalSignalLogRepo:
    """Thin shadow-log persistence for the emotional signal detector."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(
        self,
        *,
        turn_id: UUID,
        vip_id: UUID | None,
        signal: EmotionalSignalRecord,
    ) -> None:
        async with self._sf() as session:
            row = EmotionalSignalLog(
                turn_id=turn_id,
                vip_id=vip_id,
                signal_type=signal.signal_type,
                intensity=signal.intensity,
                should_trigger_synthesis=signal.should_trigger_synthesis,
                should_escalate_to_owner=signal.should_escalate_to_owner,
                pipeline_would_have_escalated=signal.pipeline_would_have_escalated,
            )
            session.add(row)
            await session.commit()

    async def list_by_vip(self, vip_id: UUID) -> list[EmotionalSignalRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(EmotionalSignalLog)
                .where(EmotionalSignalLog.vip_id == vip_id)
                .order_by(EmotionalSignalLog.created_at.desc())
            )
            return [
                emotional_signal_log_orm_to_record(r) for r in result.scalars()
            ]

    async def purge_expired(self, ttl_days: int) -> int:
        batch_size = 1000
        cutoff = func.now() - text(":ttl_days * INTERVAL '1 day'")
        total_deleted = 0

        while True:
            async with self._sf() as session:
                batch_ids = (
                    select(EmotionalSignalLog.id)
                    .where(EmotionalSignalLog.created_at < cutoff)
                    .limit(batch_size)
                )
                stmt = delete(EmotionalSignalLog).where(
                    EmotionalSignalLog.id.in_(batch_ids)
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


__all__ = [
    "SqlEmotionalSignalLogRepo",
    "emotional_signal_log_orm_to_record",
]
