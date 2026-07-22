"""SqlEscalationStore."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import EscalationEvent


class SqlEscalationStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self, turn_id: UUID, *, tipo: str, motivo: str | None
    ) -> None:
        async with self._sf() as session:
            session.add(
                EscalationEvent(
                    id=uuid4(),
                    turn_id=turn_id,
                    tipo=tipo,
                    motivo=motivo,
                    notificado=False,
                )
            )
            await session.commit()

    async def mark_notified(self, turn_id: UUID) -> None:
        async with self._sf() as session:
            await session.execute(
                update(EscalationEvent)
                .where(EscalationEvent.turn_id == turn_id)
                .values(notificado=True)
            )
            await session.commit()


__all__ = ["SqlEscalationStore"]
