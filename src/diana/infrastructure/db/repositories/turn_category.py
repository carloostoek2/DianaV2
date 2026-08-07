"""TurnCategoryLogRepo — per-turn category classification (Fase 2 writer, schema-only)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import TurnCategoryLogRecord
from diana.infrastructure.db.models import TurnCategoryLog


def turn_category_log_orm_to_record(row: TurnCategoryLog) -> TurnCategoryLogRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return TurnCategoryLogRecord(
        id=row.id,
        turn_id=row.turn_id,
        category=row.category,
        chat_id=row.chat_id,
        vip_id=row.vip_id,
        created_at=row.created_at,
    )


class SqlTurnCategoryLogRepo:
    """Thin classification log — no classifier logic here (Fase 2)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(self, record: TurnCategoryLogRecord) -> TurnCategoryLogRecord:
        values: dict[str, object] = dict(
            turn_id=record.turn_id,
            category=record.category,
            chat_id=record.chat_id,
            vip_id=record.vip_id,
        )
        # Omit ``id`` / ``created_at`` when None so the server defaults
        # (``gen_random_uuid()`` / ``now()``) fill them — explicit NULLs would
        # violate the NOT NULL columns.
        if record.id is not None:
            values["id"] = record.id
        if record.created_at is not None:
            values["created_at"] = record.created_at
        async with self._sf() as session:
            row = TurnCategoryLog(**values)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return turn_category_log_orm_to_record(row)

    async def list_recent(
        self, chat_id: int, limit: int = 20
    ) -> list[TurnCategoryLogRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(TurnCategoryLog)
                .where(TurnCategoryLog.chat_id == chat_id)
                .order_by(TurnCategoryLog.created_at.desc())
                .limit(limit)
            )
            return [turn_category_log_orm_to_record(r) for r in result.scalars()]

    async def purge_expired(self, ttl_days: int) -> int:
        batch_size = 1000
        cutoff = func.now() - text(":ttl_days * INTERVAL '1 day'")
        total_deleted = 0

        while True:
            async with self._sf() as session:
                batch_ids = (
                    select(TurnCategoryLog.id)
                    .where(TurnCategoryLog.created_at < cutoff)
                    .limit(batch_size)
                )
                stmt = delete(TurnCategoryLog).where(
                    TurnCategoryLog.id.in_(batch_ids)
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


__all__ = ["SqlTurnCategoryLogRepo", "turn_category_log_orm_to_record"]
