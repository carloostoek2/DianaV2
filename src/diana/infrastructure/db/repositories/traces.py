"""SqlTraceStore — TRACE_KEYS upsert + delivery_result UPDATE."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.cognitive.ports import TRACE_KEYS, TRACE_KEY_TO_COLUMN, to_jsonable
from diana.infrastructure.db.models import PipelineTrace, Turn

# Columns that accept TRACE_KEYS values.
_TRACE_COLUMNS = frozenset(TRACE_KEY_TO_COLUMN.values())


class SqlTraceStore:
    """TraceStore + DeliveryResultWriter + TraceReader against pipeline_traces."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

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


__all__ = ["SqlTraceStore"]
