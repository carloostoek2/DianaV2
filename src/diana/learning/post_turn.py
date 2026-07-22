"""Post-turn learning for F1: TRACE_KEYS completeness check only (no Staging)."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from diana.application.ports import TraceReader
from diana.cognitive.ports import TRACE_KEYS

logger = logging.getLogger("diana.learning")


class PostTurnReport(BaseModel):
    """Result of post-turn trace completeness check."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    complete: bool
    missing: list[str] = Field(default_factory=list)


class LearningService:
    """Ensure cognitive TRACE_KEYS are present after the application decision path.

    F1 does **not** write Staging candidates or promote examples.
    """

    def __init__(self, traces: TraceReader) -> None:
        self._traces = traces

    async def run_post_turn(self, turn_id: UUID) -> PostTurnReport:
        present = await self._traces.get_trace_keys(turn_id)
        missing = [k for k in TRACE_KEYS if k not in present]
        report = PostTurnReport(
            turn_id=turn_id,
            complete=not missing,
            missing=missing,
        )
        logger.info(
            "post_turn",
            extra={
                "turn_id": str(turn_id),
                "complete": report.complete,
                "missing": report.missing,
            },
        )
        return report


__all__ = ["LearningService", "PostTurnReport"]
