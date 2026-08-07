"""SqlTraceStore — TRACE_KEYS upsert + delivery_result UPDATE + trace reader."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, literal, select, text, update
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
        channel_type = turn.channel_type if turn else "vip"
        row = PipelineTrace(
            id=uuid4(),
            turn_id=turn_id,
            vip_id=vip_id,
            chat_id=chat_id,
            channel_type=channel_type,
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
                PipelineTrace.channel_type,
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
                "channel_type": pt.channel_type,
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


    async def get_recent_intents(
        self,
        chat_id: int,
        *,
        limit: int = 2,
        exclude_turn_id: UUID | None = None,
    ) -> list[str]:
        """Return prior-turn comprehension intents for chat (newest first).

        Skips rows with missing/empty intent. Optional ``exclude_turn_id`` drops
        the current turn after comprehension was stored.
        """
        if limit <= 0:
            return []
        stmt = (
            select(PipelineTrace.turn_id, PipelineTrace.comprehension)
            .where(
                PipelineTrace.chat_id == chat_id,
                PipelineTrace.comprehension.is_not(None),
            )
            .order_by(PipelineTrace.created_at.desc())
        )
        if exclude_turn_id is not None:
            stmt = stmt.where(PipelineTrace.turn_id != exclude_turn_id)
        # Oversample then filter empties so limit is on non-empty intents.
        stmt = stmt.limit(max(limit * 4, limit))
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = result.all()
        out: list[str] = []
        for _turn_id, comprehension in rows:
            if not isinstance(comprehension, dict):
                continue
            intent = comprehension.get("intent")
            if intent is None:
                continue
            intent_s = str(intent).strip()
            if not intent_s:
                continue
            out.append(intent_s)
            if len(out) >= limit:
                break
        return out

    async def get_recent_comprehension(
        self,
        chat_id: int,
        *,
        limit: int = 5,
        exclude_turn_id: UUID | None = None,
    ) -> list[dict]:
        """Prior-turn comprehension dicts for chat (newest first).

        Emotional baseline for the signal detector: reads
        ``pipeline_traces.comprehension`` (the only table with per-turn
        emotion). Skips rows with missing/empty comprehension. Optional
        ``exclude_turn_id`` drops the current turn after comprehension was
        stored (mirror of ``get_recent_intents``).
        """
        if limit <= 0:
            return []
        stmt = (
            select(PipelineTrace.turn_id, PipelineTrace.comprehension)
            .where(
                PipelineTrace.chat_id == chat_id,
                PipelineTrace.comprehension.is_not(None),
            )
            .order_by(PipelineTrace.created_at.desc())
        )
        if exclude_turn_id is not None:
            stmt = stmt.where(PipelineTrace.turn_id != exclude_turn_id)
        # Oversample then filter empties so limit is on non-empty comprehensions.
        stmt = stmt.limit(max(limit * 4, limit))
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = result.all()
        out: list[dict] = []
        for _turn_id, comprehension in rows:
            if not isinstance(comprehension, dict):
                continue
            if not comprehension:
                continue
            out.append(comprehension)
            if len(out) >= limit:
                break
        return out

    async def purge_expired(self, ttl_days: int | None = None) -> int:
        """Delete pipeline_traces rows older than TTL, batched.

        Uses LIMIT 1000 per batch with separate sessions to avoid long-lived
        transactions and table locks. Returns total rows deleted.

        Note: SQLAlchemy's ``delete()`` has no ``.limit()``; batching is done
        via ``DELETE ... WHERE id IN (SELECT id ... LIMIT 1000)``.
        """
        days = ttl_days if ttl_days is not None else self._ttl_days
        batch_size = 1000

        cutoff = func.now() - text(":ttl_days * INTERVAL '1 day'")
        total_deleted = 0

        while True:
            async with self._sf() as session:
                # Delete has no .limit() and no .params(); batch via subquery
                # and pass bind values to execute().
                batch_ids = (
                    select(PipelineTrace.id)
                    .where(PipelineTrace.created_at < cutoff)
                    .limit(batch_size)
                )
                stmt = delete(PipelineTrace).where(PipelineTrace.id.in_(batch_ids))
                result = await session.execute(stmt, {"ttl_days": days})
                await session.commit()
                batch_count = result.rowcount if result.rowcount and result.rowcount > 0 else 0
                total_deleted += batch_count
                if batch_count < batch_size:
                    break

        if total_deleted:
            import logging
            _log = logging.getLogger("diana.infrastructure")
            _log.info("purge_expired_complete", extra={"deleted": total_deleted, "ttl_days": days})

        return total_deleted


__all__ = ["SqlTraceStore"]
