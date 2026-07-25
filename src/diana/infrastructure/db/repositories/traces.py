"""SqlTraceStore — TRACE_KEYS upsert + delivery_result UPDATE + trace reader."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, literal, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.cognitive.ports import TRACE_KEYS, TRACE_KEY_TO_COLUMN, to_jsonable
from diana.infrastructure.db.models import PipelineTrace, Turn, Vip

# Columns that accept TRACE_KEYS values.
_TRACE_COLUMNS = frozenset(TRACE_KEY_TO_COLUMN.values())


class SqlTraceStore:
    """TraceStore + DeliveryResultWriter + TraceReader against pipeline_traces."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], ttl_days: int = 30) -> None:
        self._sf = session_factory
        self._ttl_days = ttl_days

    async def _ensure_row(
        self, session: AsyncSession, turn_id: UUID
    ) -> PipelineTrace:
        result = await session.execute(
            select(PipelineTrace).where(PipelineTrace.turn_id == turn_id)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row
        turn = await session.get(Turn, turn_id)
        chat_id = turn.chat_id if turn else 0
        vip_id = turn.vip_id if turn else None
        row = PipelineTrace(
            id=uuid4(),
            turn_id=turn_id,
            vip_id=vip_id,
            chat_id=chat_id,
        )
        session.add(row)
        await session.flush()
        return row

    async def store(self, turn_id: UUID, key: str, value: Any) -> None:
        col = TRACE_KEY_TO_COLUMN.get(key, key)
        if col not in _TRACE_COLUMNS:
            return
        payload = to_jsonable(value)
        async with self._sf() as session:
            row = await self._ensure_row(session, turn_id)
            setattr(row, col, payload)
            await session.commit()

    async def set_delivery_result(self, turn_id: UUID, result: dict) -> None:
        async with self._sf() as session:
            row = await self._ensure_row(session, turn_id)
            row.delivery_result = dict(result)
            await session.commit()

    async def get_trace_keys(self, turn_id: UUID) -> set[str]:
        async with self._sf() as session:
            result = await session.execute(
                select(PipelineTrace).where(PipelineTrace.turn_id == turn_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return set()
            present: set[str] = set()
            for key in TRACE_KEYS:
                col = TRACE_KEY_TO_COLUMN[key]
                if getattr(row, col, None) is not None:
                    present.add(key)
            return present


    async def get_recent_turns(
        self,
        limit: int = 10,
        offset: int = 0,
        chat_id: int | None = None,
    ) -> list[dict]:
        """Return recent turns summary with VIP display_name, ordered by created_at DESC."""
        cutoff = func.now() - text(":ttl_days * INTERVAL '1 day'")
        stmt = (
            select(
                PipelineTrace.turn_id,
                PipelineTrace.chat_id,
                PipelineTrace.created_at,
                PipelineTrace.decision,
                PipelineTrace.prompt_text.label("message_text"),
                Vip.display_name,
                Turn.status,
                literal(False).label("correction_applied"),
            )
            .outerjoin(Turn, PipelineTrace.turn_id == Turn.id)
            .outerjoin(Vip, PipelineTrace.vip_id == Vip.id)
            .where(PipelineTrace.created_at >= cutoff)
            .order_by(PipelineTrace.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if chat_id is not None:
            stmt = stmt.where(PipelineTrace.chat_id == chat_id)
        # Bind ttl_days as a parameter to avoid SQL injection.
        stmt = stmt.params(ttl_days=self._ttl_days)
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = result.all()
            return [dict(r._mapping) for r in rows]

    async def get_full_trace(self, turn_id: UUID) -> dict | None:
        """Return the full pipeline_trace row joined with turn status/error."""
        stmt = (
            select(
                PipelineTrace,
                Turn.status,
                Turn.error,
            )
            .outerjoin(Turn, PipelineTrace.turn_id == Turn.id)
            .where(PipelineTrace.turn_id == turn_id)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.one_or_none()
            if row is None:
                return None
            pt, status, error = row
            data: dict[str, Any] = {
                "turn_id": pt.turn_id,
                "chat_id": pt.chat_id,
                "vip_id": pt.vip_id,
                "created_at": pt.created_at,
                "comprehension": pt.comprehension,
                "plan": pt.plan,
                "retrieved": pt.retrieved,
                "prompt_text": pt.prompt_text,
                "generated_text": pt.generated_text,
                "evaluation": pt.evaluation,
                "decision": pt.decision,
                "delivery_result": pt.delivery_result,
                "timings": pt.timings,
                "status": status,
                "error": error,
            }
            return data

    async def count_recent(self, chat_id: int | None = None) -> int:
        """Return count of pipeline_traces within TTL."""
        cutoff = func.now() - text(":ttl_days * INTERVAL '1 day'")
        stmt = (
            select(func.count())
            .select_from(PipelineTrace)
            .where(PipelineTrace.created_at >= cutoff)
        )
        if chat_id is not None:
            stmt = stmt.where(PipelineTrace.chat_id == chat_id)
        stmt = stmt.params(ttl_days=self._ttl_days)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return result.scalar_one()


__all__ = ["SqlTraceStore"]
