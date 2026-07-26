"""PromoExecutionRepo — thin insert/query for promo_executions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import PromoExecutionRecord
from diana.infrastructure.db.models import PromoExecution


def promo_execution_orm_to_record(row: PromoExecution) -> PromoExecutionRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    sequence = row.sequence_sent
    if isinstance(sequence, list):
        seq: list[str] | dict | None = [str(item) for item in sequence]
    elif isinstance(sequence, dict):
        seq = sequence
    else:
        seq = None
    return PromoExecutionRecord(
        id=row.id,
        chat_id=row.chat_id,
        trigger_id=row.trigger_id,
        sent_at=row.sent_at,
        sequence_sent=seq,
        status=row.status,
    )


class PromoExecutionRepo:
    """Thin execution history — no eligibility / silence-window math."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(
        self,
        chat_id: int,
        trigger_id: UUID,
        sequence_sent: list[str] | None,
        status: str = "sent",
    ) -> PromoExecutionRecord:
        async with self._sf() as session:
            row = PromoExecution(
                chat_id=chat_id,
                trigger_id=trigger_id,
                sequence_sent=sequence_sent,
                status=status,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return promo_execution_orm_to_record(row)

    async def latest_for_chat_trigger(
        self, chat_id: int, trigger_id: UUID
    ) -> PromoExecutionRecord | None:
        async with self._sf() as session:
            result = await session.execute(
                select(PromoExecution)
                .where(
                    PromoExecution.chat_id == chat_id,
                    PromoExecution.trigger_id == trigger_id,
                )
                .order_by(PromoExecution.sent_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return promo_execution_orm_to_record(row) if row else None

    async def was_sent_since(
        self, chat_id: int, trigger_id: UUID, since: datetime
    ) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                select(PromoExecution.id)
                .where(
                    PromoExecution.chat_id == chat_id,
                    PromoExecution.trigger_id == trigger_id,
                    PromoExecution.status == "sent",
                    PromoExecution.sent_at >= since,
                )
                .limit(1)
            )
            return result.scalar_one_or_none() is not None


__all__ = ["PromoExecutionRepo", "promo_execution_orm_to_record"]
