"""SQL readers for MetricsAggregationService (traces + sides).

Implements MetricsTraceSource + MetricsSideSource. Read-only; no threshold
writes. Composition (Item 4) wires this into MetricsAggregationService.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import (
    DailyMessageLimit,
    GrayZoneQuery,
    PipelineTrace,
    PromoExecution,
    StagingCandidate,
)

logger = logging.getLogger("diana.infrastructure.db")

__all__ = [
    "SqlMetricsDataSource",
    "trace_row_to_metrics_dict",
    "week_window_utc",
]


def week_window_utc(week_start: date, week_end: date) -> tuple[datetime, datetime]:
    """Convert week date bounds to timezone-aware UTC half-open interval."""
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)
    end = datetime(week_end.year, week_end.month, week_end.day, tzinfo=UTC)
    return start, end


def trace_row_to_metrics_dict(
    *,
    turn_id: UUID,
    decision: object,
    timings: object,
    created_at: datetime | None,
) -> dict:
    """Map a pipeline_traces row subset to the service dict shape."""
    return {
        "turn_id": turn_id,
        "decision": decision if isinstance(decision, dict) else decision,
        "timings": timings if isinstance(timings, dict) else timings,
        "created_at": created_at,
    }


class SqlMetricsDataSource:
    """MetricsTraceSource + MetricsSideSource against F2/F3 tables."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def iter_week_traces(
        self, week_start: date, week_end: date
    ) -> list[dict]:
        start, end = week_window_utc(week_start, week_end)
        async with self._sf() as session:
            result = await session.execute(
                select(
                    PipelineTrace.turn_id,
                    PipelineTrace.decision,
                    PipelineTrace.timings,
                    PipelineTrace.created_at,
                ).where(
                    and_(
                        PipelineTrace.created_at >= start,
                        PipelineTrace.created_at < end,
                    )
                )
            )
            return [
                trace_row_to_metrics_dict(
                    turn_id=turn_id,
                    decision=decision,
                    timings=timings,
                    created_at=created_at,
                )
                for turn_id, decision, timings, created_at in result.all()
            ]

    async def corrected_turn_ids(self, turn_ids: list[UUID]) -> set[UUID]:
        """Turn ids that have a staging example correction candidate."""
        if not turn_ids:
            return set()
        async with self._sf() as session:
            result = await session.execute(
                select(StagingCandidate.turn_id)
                .where(
                    and_(
                        StagingCandidate.turn_id.in_(turn_ids),
                        StagingCandidate.candidate_type == "example",
                    )
                )
                .distinct()
            )
            return {row[0] for row in result.all() if row[0] is not None}

    async def gray_zone_questions(
        self, week_start: date, week_end: date
    ) -> list[str]:
        start, end = week_window_utc(week_start, week_end)
        async with self._sf() as session:
            result = await session.execute(
                select(GrayZoneQuery.question).where(
                    and_(
                        GrayZoneQuery.created_at >= start,
                        GrayZoneQuery.created_at < end,
                    )
                )
            )
            return [str(q) for (q,) in result.all() if q is not None]

    async def promo_stats(
        self, week_start: date, week_end: date
    ) -> tuple[int, int, int]:
        """Return (sent_count, unique_chats, repeat_count) for the week window."""
        start, end = week_window_utc(week_start, week_end)
        async with self._sf() as session:
            sent = await session.scalar(
                select(func.count())
                .select_from(PromoExecution)
                .where(
                    and_(
                        PromoExecution.sent_at >= start,
                        PromoExecution.sent_at < end,
                    )
                )
            )
            unique = await session.scalar(
                select(func.count(func.distinct(PromoExecution.chat_id))).where(
                    and_(
                        PromoExecution.sent_at >= start,
                        PromoExecution.sent_at < end,
                    )
                )
            )
            sent_count = int(sent or 0)
            unique_chats = int(unique or 0)
            repeat_count = max(0, sent_count - unique_chats)
            return sent_count, unique_chats, repeat_count

    async def count_atencion_turns_since(self, since_utc: datetime) -> int:
        """Count atencion pipeline_traces created at/after ``since_utc``."""
        async with self._sf() as session:
            result = await session.scalar(
                select(func.count())
                .select_from(PipelineTrace)
                .where(
                    and_(
                        PipelineTrace.channel_type == "atencion",
                        PipelineTrace.created_at >= since_utc,
                    )
                )
            )
            return int(result or 0)

    async def count_atencion_limit_reached_on(self, fecha_local: date) -> int:
        """Count chats that reached the 20-message cap on ``fecha_local``."""
        async with self._sf() as session:
            result = await session.scalar(
                select(func.count())
                .select_from(DailyMessageLimit)
                .where(
                    and_(
                        DailyMessageLimit.fecha_local == fecha_local,
                        DailyMessageLimit.count >= 20,
                    )
                )
            )
            return int(result or 0)
