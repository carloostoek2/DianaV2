"""SqlBusinessConnectionStore — persistent business connection repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from diana.application.ports import BusinessConnectionRecord
from diana.infrastructure.db.models import Base


class BusinessConnection(Base):
    """ORM model for business_connections table (inline to avoid touching models.py)."""

    __tablename__ = "business_connections"

    business_connection_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    can_reply: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


def _orm_to_record(row: BusinessConnection) -> BusinessConnectionRecord:
    return BusinessConnectionRecord(
        business_connection_id=row.business_connection_id,
        user_id=row.user_id,
        user_chat_id=row.user_chat_id,
        date=row.date,
        can_reply=row.can_reply,
        is_enabled=row.is_enabled,
    )


class SqlBusinessConnectionStore:
    """Postgres-backed BusinessConnectionStore using session.merge() for upsert."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def upsert(self, record: BusinessConnectionRecord) -> BusinessConnectionRecord:
        async with self._sf() as session:
            orm_row = BusinessConnection(
                business_connection_id=record.business_connection_id,
                user_id=record.user_id,
                user_chat_id=record.user_chat_id,
                date=record.date,
                can_reply=record.can_reply,
                is_enabled=record.is_enabled,
            )
            orm_row.updated_at = datetime.now(UTC)
            merged = await session.merge(orm_row)
            result = _orm_to_record(merged)
            await session.commit()
            return result


__all__ = [
    "BusinessConnection",
    "SqlBusinessConnectionStore",
]
