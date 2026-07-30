"""SqlRuntimeTimerStore — persistent runtime timer repository for crash recovery."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Float, Index, Text, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from diana.application.ports import RuntimeTimerRecord
from diana.infrastructure.db.models import Base


class RuntimeTimer(Base):
    """ORM model for runtime_timers table (inline to avoid touching models.py)."""

    __tablename__ = "runtime_timers"
    __table_args__ = (Index("ix_runtime_timers_status_created_at", "status", "created_at"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    turn_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    delivery_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_delay_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


def _orm_to_record(row: RuntimeTimer) -> RuntimeTimerRecord:
    return RuntimeTimerRecord(
        id=row.id,
        chat_id=row.chat_id,
        turn_id=row.turn_id,
        delivery_id=row.delivery_id,
        scheduled_at=row.scheduled_at,
        initial_delay_seconds=row.initial_delay_seconds,
        status=row.status,
        created_at=row.created_at,
    )


class SqlRuntimeTimerStore:
    """Postgres-backed RuntimeTimerStore following SqlPendingDeliveryStore pattern."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_active(self, record: RuntimeTimerRecord) -> RuntimeTimerRecord:
        async with self._sf() as session:
            row = RuntimeTimer(
                id=record.id,
                chat_id=record.chat_id,
                turn_id=record.turn_id,
                delivery_id=record.delivery_id,
                scheduled_at=record.scheduled_at,
                initial_delay_seconds=record.initial_delay_seconds,
                status=record.status or "active",
                created_at=record.created_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _orm_to_record(row)

    async def mark_completed(self, timer_id: UUID) -> bool:
        async with self._sf() as session:
            row = await session.get(RuntimeTimer, timer_id)
            if row is None:
                return False
            row.status = "completed"
            await session.commit()
            return True

    async def list_active(self) -> list[RuntimeTimerRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(RuntimeTimer).where(RuntimeTimer.status == "active")
            )
            return [_orm_to_record(r) for r in result.scalars().all()]

    async def delete_for_turn(self, turn_id: UUID) -> None:
        async with self._sf() as session:
            result = await session.execute(
                select(RuntimeTimer).where(RuntimeTimer.turn_id == turn_id)
            )
            for row in result.scalars().all():
                await session.delete(row)
            await session.commit()


__all__ = [
    "RuntimeTimer",
    "SqlRuntimeTimerStore",
    "_orm_to_record",
]
