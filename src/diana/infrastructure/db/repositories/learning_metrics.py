"""SqlLearningMetricsRepo — EAV weekly learning_metrics (global vip_id=NULL).

replace_week is idempotent: delete existing global rows for week_start then insert.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import LearningMetric

__all__ = [
    "SqlLearningMetricsRepo",
    "metric_rows_to_week_dict",
    "week_recorded_at",
]


def week_recorded_at(week_start: date) -> datetime:
    """Canonical timestamp for a week: Monday 00:00 UTC."""
    return datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)


def metric_rows_to_week_dict(
    rows: list[tuple[str, float]],
) -> dict[str, float]:
    """Pivot (metric_name, value) pairs → dict (last write wins on duplicate)."""
    out: dict[str, float] = {}
    for name, value in rows:
        out[str(name)] = float(value)
    return out


class SqlLearningMetricsRepo:
    """LearningMetricsStore against learning_metrics EAV table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def replace_week(
        self, week_start: date, values: dict[str, float]
    ) -> None:
        recorded = week_recorded_at(week_start)
        week_end = recorded + timedelta(days=7)
        async with self._sf() as session:
            await session.execute(
                delete(LearningMetric).where(
                    and_(
                        LearningMetric.vip_id.is_(None),
                        LearningMetric.recorded_at >= recorded,
                        LearningMetric.recorded_at < week_end,
                    )
                )
            )
            for name, value in values.items():
                session.add(
                    LearningMetric(
                        vip_id=None,
                        metric_name=str(name),
                        value=float(value),
                        recorded_at=recorded,
                    )
                )
            await session.commit()

    async def get_week(self, week_start: date) -> dict[str, float]:
        recorded = week_recorded_at(week_start)
        week_end = recorded + timedelta(days=7)
        async with self._sf() as session:
            result = await session.execute(
                select(LearningMetric.metric_name, LearningMetric.value).where(
                    and_(
                        LearningMetric.vip_id.is_(None),
                        LearningMetric.recorded_at >= recorded,
                        LearningMetric.recorded_at < week_end,
                    )
                )
            )
            return metric_rows_to_week_dict(
                [(str(n), float(v)) for n, v in result.all()]
            )

    async def get_previous_week(self, week_start: date) -> dict[str, float]:
        prev = week_start - timedelta(days=7)
        return await self.get_week(prev)

    async def list_weeks(self, limit: int = 12) -> list[date]:
        """Distinct Monday dates (global metrics) newest first."""
        async with self._sf() as session:
            result = await session.execute(
                select(LearningMetric.recorded_at)
                .where(LearningMetric.vip_id.is_(None))
                .distinct()
                .order_by(LearningMetric.recorded_at.desc())
                .limit(int(limit))
            )
            weeks: list[date] = []
            seen: set[date] = set()
            for (ts,) in result.all():
                if ts is None:
                    continue
                d = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
                if d not in seen:
                    seen.add(d)
                    weeks.append(d)
            return weeks
