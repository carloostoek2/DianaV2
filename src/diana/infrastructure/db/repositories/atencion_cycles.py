"""SqlAtencionCycleStore — per-chat atencion lifecycle (F4).

One row per non-VIP chat that received the promo. ``started_at`` anchors the
30-day linear window; ``closed_at``/``close_reason`` terminate the cycle early
on payment intent (owner delivers manually afterwards). Re-triggers of the
promo never reset ``started_at`` (``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import AtencionCycle

__all__ = ["SqlAtencionCycleStore"]


class SqlAtencionCycleStore:
    """AtencionCycleStore against ``atencion_cycles`` (chat_id PK)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def start_if_absent(self, chat_id: int, *, now: datetime) -> None:
        """Open the cycle on the first promo delivery; never resets an open one."""
        stmt = (
            insert(AtencionCycle)
            .values(chat_id=chat_id, started_at=now)
            .on_conflict_do_nothing(index_elements=["chat_id"])
        )
        async with self._sf() as session:
            await session.execute(stmt)
            await session.commit()

    async def is_active(
        self, chat_id: int, *, since: datetime, now: datetime
    ) -> bool:
        """True when the 30-day window is open and the cycle is not closed."""
        stmt = (
            select(AtencionCycle.chat_id)
            .where(
                AtencionCycle.chat_id == chat_id,
                AtencionCycle.started_at >= since,
                AtencionCycle.closed_at.is_(None),
            )
            .limit(1)
        )
        async with self._sf() as session:
            row = (await session.execute(stmt)).first()
            return row is not None

    async def close_payment(self, chat_id: int, *, now: datetime) -> None:
        """Close an open cycle on payment intent (idempotent per chat)."""
        stmt = (
            update(AtencionCycle)
            .where(
                AtencionCycle.chat_id == chat_id,
                AtencionCycle.closed_at.is_(None),
            )
            .values(closed_at=now, close_reason="payment")
        )
        async with self._sf() as session:
            await session.execute(stmt)
            await session.commit()
