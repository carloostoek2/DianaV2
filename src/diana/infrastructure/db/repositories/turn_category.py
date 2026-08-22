"""TurnCategoryLogRepo — per-turn category classification (Fase 2 writer, schema-only)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import TurnCategoryLogRecord
from diana.infrastructure.db.models import PipelineTrace, TurnCategoryLog


def turn_category_log_orm_to_record(row: TurnCategoryLog) -> TurnCategoryLogRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return TurnCategoryLogRecord(
        id=row.id,
        turn_id=row.turn_id,
        category=row.category,
        chat_id=row.chat_id,
        vip_id=row.vip_id,
        would_autonomous=row.would_autonomous,
        confidence=row.confidence,
        created_at=row.created_at,
    )


class SqlTurnCategoryLogRepo:
    """Thin classification log — no classifier logic here (Fase 2)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_by_turn_id(self, turn_id: UUID) -> TurnCategoryLogRecord | None:
        """Resolve the classification of ONE turn (turn_id is UNIQUE).

        Fase 5 correction event: ``TrustBudgetService.record_correction`` maps a
        ``turn_id`` back to its (vip_id, category) via this reader. ``None``
        when the turn was never classified (pre-Fase-2 rows / no row).
        """
        async with self._sf() as session:
            result = await session.execute(
                select(TurnCategoryLog).where(TurnCategoryLog.turn_id == turn_id)
            )
            row = result.scalar_one_or_none()
            return (
                turn_category_log_orm_to_record(row) if row is not None else None
            )

    async def insert(self, record: TurnCategoryLogRecord) -> TurnCategoryLogRecord:
        values: dict[str, object] = dict(
            turn_id=record.turn_id,
            category=record.category,
            chat_id=record.chat_id,
            vip_id=record.vip_id,
            would_autonomous=record.would_autonomous,
            confidence=record.confidence,
        )
        # Omit ``id`` / ``created_at`` when None so the server defaults
        # (``gen_random_uuid()`` / ``now()``) fill them — explicit NULLs would
        # violate the NOT NULL columns. ``would_autonomous`` / ``confidence``
        # are NULL-able → explicit None is valid (unlike id/created_at).
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

    async def list_would_autonomous(
        self, limit: int = 10
    ) -> list[TurnCategoryLogRecord]:
        """Most recent turns where the fast-lane would have auto-sent (shadow).

        Owner consult surface (``AdminShadowService.render_drafts``): ordered
        newest-first, all VIPs.
        """
        async with self._sf() as session:
            result = await session.execute(
                select(TurnCategoryLog)
                .where(TurnCategoryLog.would_autonomous.is_(True))
                .order_by(TurnCategoryLog.created_at.desc())
                .limit(limit)
            )
            return [turn_category_log_orm_to_record(r) for r in result.scalars()]

    async def list_recent_with_draft(self, limit: int = 10) -> list[dict]:
        """Recent classifications joined with their generated draft.

        Owner consult surface (``AdminShadowService.render_decisions``): every
        row carries the draft the pipeline actually generated (the same text
        the owner approves), so the shadow verdict can be compared with the
        real message side by side. ``draft`` is None when the turn has no
        trace row yet (or the generator never produced text, e.g. template
        cut without a stored text).
        """
        stmt = (
            select(
                TurnCategoryLog.turn_id,
                TurnCategoryLog.vip_id,
                TurnCategoryLog.chat_id,
                TurnCategoryLog.category,
                TurnCategoryLog.confidence,
                TurnCategoryLog.would_autonomous,
                TurnCategoryLog.created_at,
                PipelineTrace.generated_text.label("draft"),
            )
            .outerjoin(
                PipelineTrace, PipelineTrace.turn_id == TurnCategoryLog.turn_id
            )
            .order_by(TurnCategoryLog.created_at.desc())
            .limit(limit)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [dict(r._mapping) for r in result.all()]

    async def daily_counts(self, days: int = 7) -> list[dict]:
        """Per-day totals over the last ``days`` days (shadow consult surface).

        Returns ``[{day: date, total: int, autonomous: int}]`` oldest-first.
        ``autonomous`` counts rows where the fast-lane would have auto-sent.
        """
        cutoff = func.now() - text(":days * INTERVAL '1 day'")
        day_col = func.date_trunc("day", TurnCategoryLog.created_at).label("day")
        stmt = (
            select(
                day_col,
                func.count().label("total"),
                func.count()
                .filter(TurnCategoryLog.would_autonomous.is_(True))
                .label("autonomous"),
            )
            .where(TurnCategoryLog.created_at >= cutoff)
            .group_by(day_col)
            .order_by(day_col)
        )
        stmt = stmt.params(days=days)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [
                {
                    "day": row.day,
                    "total": int(row.total),
                    "autonomous": int(row.autonomous),
                }
                for row in result.all()
            ]

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
