"""SqlTurnStore — terminal latch parity with InMemoryTurnStore."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import TurnRecord
from diana.cognitive.models import TERMINAL_TURN_STATUSES, TurnStatus, parse_turn_status
from diana.infrastructure.db.models import Turn


def is_terminal_status(status: str) -> bool:
    try:
        return parse_turn_status(status) in TERMINAL_TURN_STATUSES
    except ValueError:
        return False


def apply_terminal_latch(
    current_status: str, new_status: str
) -> tuple[bool, str]:
    """Return (changed, effective_status). Terminal rows refuse non-identity transitions."""
    if is_terminal_status(current_status) and current_status != new_status:
        return False, current_status
    return True, new_status


def turn_orm_to_record(row: Turn) -> TurnRecord:
    return TurnRecord(
        id=row.id,
        chat_id=row.chat_id,
        status=row.status,
        vip_id=row.vip_id,
        trigger_message_id=row.trigger_message_id,
        superseded_by=row.superseded_by,
        error=row.error,
    )


class SqlTurnStore:
    """Postgres-backed TurnStore with terminal status latch."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(self, turn: TurnRecord) -> TurnRecord:
        async with self._sf() as session:
            row = Turn(
                id=turn.id,
                chat_id=turn.chat_id,
                status=turn.status,
                vip_id=turn.vip_id,
                trigger_message_id=turn.trigger_message_id,
                superseded_by=turn.superseded_by,
                error=turn.error,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return turn_orm_to_record(row)

    async def get(self, turn_id: UUID) -> TurnRecord | None:
        async with self._sf() as session:
            row = await session.get(Turn, turn_id)
            return turn_orm_to_record(row) if row else None

    async def list_non_terminal(self, chat_id: int) -> list[TurnRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(Turn).where(Turn.chat_id == chat_id)
            )
            rows = result.scalars().all()
            return [
                turn_orm_to_record(r)
                for r in rows
                if not is_terminal_status(r.status)
            ]

    async def list_all_non_terminal(self) -> list[TurnRecord]:
        async with self._sf() as session:
            result = await session.execute(select(Turn))
            rows = result.scalars().all()
            return [
                turn_orm_to_record(r)
                for r in rows
                if not is_terminal_status(r.status)
            ]

    async def transition(
        self,
        turn_id: UUID,
        status: str,
        *,
        superseded_by: UUID | None = None,
        error: str | None = None,
    ) -> TurnRecord:
        new_status = status.value if isinstance(status, TurnStatus) else str(status)
        async with self._sf() as session:
            row = await session.get(Turn, turn_id)
            if row is None:
                raise KeyError(f"turn not found: {turn_id}")
            changed, effective = apply_terminal_latch(row.status, new_status)
            if not changed:
                return turn_orm_to_record(row)
            row.status = effective
            if superseded_by is not None:
                row.superseded_by = superseded_by
            if error is not None:
                row.error = error
            await session.commit()
            await session.refresh(row)
            return turn_orm_to_record(row)


__all__ = [
    "SqlTurnStore",
    "apply_terminal_latch",
    "is_terminal_status",
    "turn_orm_to_record",
]
