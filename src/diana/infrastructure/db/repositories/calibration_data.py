"""SQL readers for CalibrationService (traces + staging + generated texts).

Implements CalibrationTraceSource + DriftTextSource. No threshold writes.
Jobs/composition wire this into CalibrationService (Item 4).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.calibration_service import CalibrationSample
from diana.infrastructure.db.models import PipelineTrace, StagingCandidate

logger = logging.getLogger("diana.infrastructure.db")

__all__ = [
    "SqlCalibrationDataSource",
    "parse_evaluation_dims",
    "row_to_calibration_sample",
]

_REQUIRED_DIMS = ("safety", "doctrine", "naturalness")


def parse_evaluation_dims(evaluation: object) -> dict[str, float] | None:
    """Extract safety/doctrine/naturalness floats from evaluation JSON.

    Returns None when any required dim is missing or non-numeric.
    """
    if not isinstance(evaluation, dict):
        return None
    out: dict[str, float] = {}
    for dim in _REQUIRED_DIMS:
        raw = evaluation.get(dim)
        if not isinstance(raw, (int, float)):
            return None
        out[dim] = float(raw)
    return out


def row_to_calibration_sample(
    *,
    turn_id: UUID,
    evaluation: object,
    corrected: bool,
) -> CalibrationSample | None:
    """Map a trace row + correction flag to CalibrationSample (or skip)."""
    dims = parse_evaluation_dims(evaluation)
    if dims is None:
        return None
    return CalibrationSample(
        turn_id=turn_id,
        safety=dims["safety"],
        doctrine=dims["doctrine"],
        naturalness=dims["naturalness"],
        corrected=corrected,
    )


class SqlCalibrationDataSource:
    """CalibrationTraceSource + DriftTextSource against pipeline_traces."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_evaluated_samples(
        self, *, window_days: int
    ) -> list[CalibrationSample]:
        """Samples in [now - window_days, now] with full evaluation dims.

        Corrected = exists staging_candidates row with candidate_type='example'
        for the same turn_id.
        """
        now = datetime.now(UTC)
        since = now - timedelta(days=int(window_days))
        corrected_exists = exists(
            select(StagingCandidate.id).where(
                and_(
                    StagingCandidate.turn_id == PipelineTrace.turn_id,
                    StagingCandidate.candidate_type == "example",
                )
            )
        )
        async with self._sf() as session:
            result = await session.execute(
                select(
                    PipelineTrace.turn_id,
                    PipelineTrace.evaluation,
                    corrected_exists.label("corrected"),
                ).where(
                    and_(
                        PipelineTrace.created_at >= since,
                        PipelineTrace.created_at <= now,
                        PipelineTrace.evaluation.is_not(None),
                        # REQ-ATN-13: calibration reads VIP traces only.
                        PipelineTrace.channel_type == "vip",
                    )
                )
            )
            samples: list[CalibrationSample] = []
            for turn_id, evaluation, corrected in result.all():
                sample = row_to_calibration_sample(
                    turn_id=turn_id,
                    evaluation=evaluation,
                    corrected=bool(corrected),
                )
                if sample is not None:
                    samples.append(sample)
            return samples

    async def sample_generated_texts(
        self, *, since_days: int, limit: int
    ) -> list[str]:
        """Up to ``limit`` non-empty generated_text from the last ``since_days``."""
        now = datetime.now(UTC)
        since = now - timedelta(days=int(since_days))
        async with self._sf() as session:
            result = await session.execute(
                select(PipelineTrace.generated_text)
                .where(
                    and_(
                        PipelineTrace.created_at >= since,
                        PipelineTrace.generated_text.is_not(None),
                        PipelineTrace.generated_text != "",
                        # REQ-ATN-13: calibration reads VIP traces only.
                        PipelineTrace.channel_type == "vip",
                    )
                )
                .order_by(func.random())
                .limit(int(limit))
            )
            return [str(t) for (t,) in result.all() if t and str(t).strip()]

    async def sample_baseline_generated_texts(
        self, *, baseline_weeks: int, limit: int
    ) -> list[str]:
        """Texts from the oldest ``baseline_weeks`` window that has generated_text."""
        async with self._sf() as session:
            min_ts = await session.scalar(
                select(func.min(PipelineTrace.created_at)).where(
                    and_(
                        PipelineTrace.generated_text.is_not(None),
                        PipelineTrace.generated_text != "",
                        # REQ-ATN-13: calibration reads VIP traces only.
                        PipelineTrace.channel_type == "vip",
                    )
                )
            )
            if min_ts is None:
                return []
            if min_ts.tzinfo is None:
                min_ts = min_ts.replace(tzinfo=UTC)
            window_end = min_ts + timedelta(weeks=int(baseline_weeks))
            result = await session.execute(
                select(PipelineTrace.generated_text)
                .where(
                    and_(
                        PipelineTrace.created_at >= min_ts,
                        PipelineTrace.created_at < window_end,
                        PipelineTrace.generated_text.is_not(None),
                        PipelineTrace.generated_text != "",
                        # REQ-ATN-13: calibration reads VIP traces only.
                        PipelineTrace.channel_type == "vip",
                    )
                )
                .order_by(func.random())
                .limit(int(limit))
            )
            return [str(t) for (t,) in result.all() if t and str(t).strip()]
