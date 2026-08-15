"""SqlLinkEventStore — persistent ledger for Lucien→Diana kick link events."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Text, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from diana.application.ports import LinkEventRecord
from diana.infrastructure.db.models import Base

logger = logging.getLogger("diana.infrastructure.db")


class LinkEvent(Base):
    """ORM model for link_events table (inline to avoid touching models.py)."""

    __tablename__ = "link_events"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    channel_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    vip_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


def link_event_orm_to_record(row: LinkEvent) -> LinkEventRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return LinkEventRecord(
        id=row.id,
        event_id=row.event_id,
        user_id=row.user_id,
        username=row.username,
        channel_id=row.channel_id,
        channel_name=row.channel_name,
        reason=row.reason,
        vip_id=row.vip_id,
        state=row.state,
        decision_at=row.decision_at,
        created_at=row.created_at,
    )


class SqlLinkEventStore:
    """Postgres-backed LinkEventStore for the kick-link decision ledger."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(self, record: LinkEventRecord) -> LinkEventRecord:
        async with self._sf() as session:
            row = LinkEvent(
                event_id=record.event_id,
                user_id=record.user_id,
                username=record.username,
                channel_id=record.channel_id,
                channel_name=record.channel_name,
                reason=record.reason,
                vip_id=record.vip_id,
                state=record.state,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return link_event_orm_to_record(row)

    async def get_by_event_id(self, event_id: str) -> LinkEventRecord | None:
        async with self._sf() as session:
            result = await session.execute(
                select(LinkEvent).where(LinkEvent.event_id == event_id)
            )
            row = result.scalar_one_or_none()
            return link_event_orm_to_record(row) if row is not None else None

    async def set_state(
        self, event_id: str, state: str, *, decision_at: datetime | None = None
    ) -> None:
        async with self._sf() as session:
            result = await session.execute(
                select(LinkEvent).where(LinkEvent.event_id == event_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise KeyError(f"link event not found: {event_id}")
            row.state = state
            if decision_at is not None:
                row.decision_at = decision_at
            await session.commit()


__all__ = ["LinkEvent", "SqlLinkEventStore", "link_event_orm_to_record"]
