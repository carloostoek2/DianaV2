"""SqlTurnStore — terminal latch parity with InMemoryTurnStore."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
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
        channel_type=row.channel_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
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
                channel_type=turn.channel_type,
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

    async def count_messages_since(
        self, vip_id: UUID, *, since: datetime | None
    ) -> int:
        """Turns of the VIP in the 'vip' channel with created_at >= since (or all).

        Fase 1 profile-synthesis activity source (A2): a message is one turn
        and an edit never creates a new turn, so ``turns`` is an exact counter
        without TTL sub-counting (``pipeline_traces`` and ``message_history``
        were rejected in the impact analysis). ``since=None`` counts every
        'vip' turn of the VIP (used when ``last_synthesized_at`` is unset).
        The boundary is inclusive (``>=``), matching memories/staging (fix
        round: unified boundary semantics).
        """
        stmt = (
            select(func.count())
            .select_from(Turn)
            .where(Turn.vip_id == vip_id, Turn.channel_type == "vip")
        )
        if since is not None:
            stmt = stmt.where(Turn.created_at >= since)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one())

    async def list_vips_with_activity_older_than(
        self, older_than: datetime, *, limit: int = 100
    ) -> list[tuple[UUID, datetime]]:
        """(vip_id, last_activity) for VIPs whose newest 'vip' turn predates older_than.

        Fase 1 scan source (``scan_inactivity``): only VIPs whose most recent
        'vip'-channel turn is OLDER than ``older_than`` are returned, newest
        last-activity first, capped at ``limit``. VIPs without any turn are
        never returned (no activity to close). The group-by needs the new
        index ``ix_turns_vip_id_created_at`` (migration 025).
        """
        stmt = (
            select(Turn.vip_id, func.max(Turn.created_at))
            .where(Turn.channel_type == "vip", Turn.vip_id.is_not(None))
            .group_by(Turn.vip_id)
            .having(func.max(Turn.created_at) < older_than)
            .order_by(func.max(Turn.created_at).desc())
            .limit(limit)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [(row[0], row[1]) for row in result.all()]

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
            # Fix round (R2): per-turn finalize timestamp — the post-turn
            # extractor uses the last transition time (DELIVERED/escalated/
            # failed) as THIS turn's own delivery/finalize upper bound.
            row.updated_at = datetime.now(UTC)
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
