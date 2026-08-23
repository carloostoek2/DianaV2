"""SqlTurnOutcomeLogRepo — turn_outcome_log persistence + on-the-fly source reads.

Fila 4 (SPEC-AUTONOMIA-CALIBRACION.md). Two surfaces in one repo:

- ``list_finished_source_turns`` — Fase A: reads the EXISTING tables
  (turns + pipeline_traces + pending_approvals + staging_candidates) to
  compute the shadow-vs-owner comparison ON THE FLY, no new schema needed.
- Fase B: ``insert`` / ``update_outcome`` / ``update_signal`` / aggregate
  readers against the new ``turn_outcome_log`` table (migration 030).

The log is a pure calibration metric (anti-contamination): it never feeds
``memories``, ``examples`` or ``vip_profile``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import TurnOutcomeLogRecord
from diana.infrastructure.db.models import (
    PendingApproval,
    PipelineTrace,
    StagingCandidate,
    Turn,
    TurnOutcomeLog,
)

__all__ = ["SqlTurnOutcomeLogRepo"]

# Finished, decided VIP turns only — superseded/failed turns never reached an
# owner outcome and are excluded from the comparison surface.
_FINISHED_STATUSES = ("delivered", "escalated")


def turn_outcome_orm_to_record(row: TurnOutcomeLog) -> TurnOutcomeLogRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return TurnOutcomeLogRecord(
        id=row.id,
        turn_id=row.turn_id,
        vip_id=row.vip_id,
        shadow_verdict=row.shadow_verdict,
        shadow_reason=row.shadow_reason,
        owner_outcome=row.owner_outcome,
        draft_score=row.draft_score,
        sent_score=row.sent_score,
        quality_delta=row.quality_delta,
        blocked_dims=row.blocked_dims or [],
        vip_signal=row.vip_signal,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlTurnOutcomeLogRepo:
    """turn_outcome_log store + finished-turn source reader (Fila 4)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ------------------------------------------------------------------
    # Fase A — on-the-fly source (existing tables, no new schema)
    # ------------------------------------------------------------------

    async def list_finished_source_turns(
        self, *, window_days: int, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Finished VIP turns (delivered/escalated) with full decision context.

        One row per turn: the evaluation/comprehension/retrieved/decision to
        re-decide with the shadow Decider, the real turn status + approval
        status, the generated draft and the owner's correction text (staging
        payload) when a correction was saved. Newest first.
        """
        since = datetime.now(UTC) - timedelta(days=int(window_days))
        correction_payload = (
            select(StagingCandidate.payload)
            .where(
                StagingCandidate.turn_id == Turn.id,
                StagingCandidate.candidate_type == "example",
                StagingCandidate.status != "discarded",
            )
            .order_by(StagingCandidate.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            select(
                Turn.id.label("turn_id"),
                Turn.vip_id,
                Turn.chat_id,
                Turn.status,
                Turn.created_at,
                PipelineTrace.generated_text.label("draft"),
                PipelineTrace.evaluation,
                PipelineTrace.comprehension,
                PipelineTrace.retrieved,
                PipelineTrace.decision,
                PendingApproval.status.label("approval_status"),
                correction_payload.label("correction_payload"),
            )
            .join(PipelineTrace, PipelineTrace.turn_id == Turn.id)
            .outerjoin(PendingApproval, PendingApproval.turn_id == Turn.id)
            .where(
                Turn.channel_type == "vip",
                Turn.status.in_(_FINISHED_STATUSES),
                Turn.created_at >= since,
            )
            .order_by(Turn.created_at.desc())
            .limit(int(limit))
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows: list[dict[str, Any]] = []
            for r in result.all():
                payload = r.correction_payload
                corrected_text = None
                if isinstance(payload, dict):
                    raw = payload.get("corrected_text")
                    if isinstance(raw, str):
                        corrected_text = raw
                rows.append(
                    {
                        "turn_id": r.turn_id,
                        "vip_id": r.vip_id,
                        "chat_id": r.chat_id,
                        "status": r.status,
                        "created_at": r.created_at,
                        "draft": r.draft,
                        "evaluation": r.evaluation,
                        "comprehension": r.comprehension,
                        "retrieved": r.retrieved,
                        "decision": r.decision,
                        "approval_status": r.approval_status,
                        "corrected_text": corrected_text,
                        "has_staging_correction": corrected_text is not None,
                    }
                )
            return rows

    # ------------------------------------------------------------------
    # Fase B — turn_outcome_log persistence (migration 030)
    # ------------------------------------------------------------------

    async def insert(self, record: TurnOutcomeLogRecord) -> TurnOutcomeLogRecord:
        """Create one outcome-log row (post-turn write; idempotent by turn_id)."""
        stmt = (
            insert(TurnOutcomeLog)
            .values(
                turn_id=record.turn_id,
                vip_id=record.vip_id,
                shadow_verdict=record.shadow_verdict,
                shadow_reason=record.shadow_reason,
                owner_outcome=record.owner_outcome,
                draft_score=record.draft_score,
                sent_score=record.sent_score,
                quality_delta=record.quality_delta,
                blocked_dims=record.blocked_dims or None,
                vip_signal=record.vip_signal,
            )
            .on_conflict_do_update(
                index_elements=[TurnOutcomeLog.turn_id],
                set_={
                    "shadow_verdict": record.shadow_verdict,
                    "shadow_reason": record.shadow_reason,
                    "owner_outcome": record.owner_outcome,
                    "draft_score": record.draft_score,
                    "sent_score": record.sent_score,
                    "quality_delta": record.quality_delta,
                    "blocked_dims": record.blocked_dims or None,
                    "vip_signal": record.vip_signal,
                    "updated_at": func.now(),
                },
            )
            .returning(TurnOutcomeLog)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return turn_outcome_orm_to_record(result.scalar_one())

    async def get_by_turn_id(self, turn_id: UUID) -> TurnOutcomeLogRecord | None:
        async with self._sf() as session:
            result = await session.execute(
                select(TurnOutcomeLog).where(TurnOutcomeLog.turn_id == turn_id)
            )
            row = result.scalar_one_or_none()
            return turn_outcome_orm_to_record(row) if row is not None else None

    async def update_outcome(
        self,
        turn_id: UUID,
        *,
        owner_outcome: str,
        sent_score: float | None,
        quality_delta: float | None,
    ) -> TurnOutcomeLogRecord | None:
        """Owner-resolution update (approved_as_is / corrected / escalated)."""
        stmt = (
            update(TurnOutcomeLog)
            .where(TurnOutcomeLog.turn_id == turn_id)
            .values(
                owner_outcome=owner_outcome,
                sent_score=sent_score,
                quality_delta=quality_delta,
                updated_at=func.now(),
            )
            .returning(TurnOutcomeLog)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalar_one_or_none()
            return turn_outcome_orm_to_record(row) if row is not None else None

    async def update_signal(
        self, turn_id: UUID, *, vip_signal: str
    ) -> TurnOutcomeLogRecord | None:
        """Reaction-window update (C3): positive/neutral/negative/silence."""
        stmt = (
            update(TurnOutcomeLog)
            .where(TurnOutcomeLog.turn_id == turn_id)
            .values(vip_signal=vip_signal, updated_at=func.now())
            .returning(TurnOutcomeLog)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalar_one_or_none()
            return turn_outcome_orm_to_record(row) if row is not None else None

    async def list_by_vip_since(
        self, vip_id: UUID, *, since: datetime, limit: int = 200
    ) -> list[TurnOutcomeLogRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(TurnOutcomeLog)
                .where(
                    TurnOutcomeLog.vip_id == vip_id,
                    TurnOutcomeLog.created_at >= since,
                )
                .order_by(TurnOutcomeLog.created_at.desc())
                .limit(int(limit))
            )
            return [turn_outcome_orm_to_record(r) for r in result.scalars()]

    async def list_recent(
        self, *, since: datetime, limit: int = 500
    ) -> list[TurnOutcomeLogRecord]:
        async with self._sf() as session:
            result = await session.execute(
                select(TurnOutcomeLog)
                .where(TurnOutcomeLog.created_at >= since)
                .order_by(TurnOutcomeLog.created_at.desc())
                .limit(int(limit))
            )
            return [turn_outcome_orm_to_record(r) for r in result.scalars()]

    async def count_safety_escalations_since(
        self, *, since: datetime
    ) -> int:
        """C6 gate: escalations caused by the safety dimension in the window."""
        async with self._sf() as session:
            result = await session.execute(
                select(func.count())
                .select_from(TurnOutcomeLog)
                .where(
                    TurnOutcomeLog.created_at >= since,
                    TurnOutcomeLog.shadow_reason == "safety_below_threshold",
                )
            )
            return int(result.scalar_one() or 0)

    async def find_pending_signal_for_chat(
        self, chat_id: int, *, since: datetime
    ) -> TurnOutcomeLogRecord | None:
        """Most recent outcome row for a chat still missing its VIP reaction.

        C3 immediate hook: when the VIP sends a follow-up, the orchestrator
        resolves the last delivered turn of the chat whose ``vip_signal`` is
        still NULL (within the reaction window) and classifies this message
        against it.
        """
        async with self._sf() as session:
            result = await session.execute(
                select(TurnOutcomeLog)
                .join(Turn, Turn.id == TurnOutcomeLog.turn_id)
                .where(
                    Turn.chat_id == chat_id,
                    TurnOutcomeLog.vip_signal.is_(None),
                    TurnOutcomeLog.created_at >= since,
                )
                .order_by(TurnOutcomeLog.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return turn_outcome_orm_to_record(row) if row is not None else None

    async def list_signal_pending(
        self, *, window_hours: int, limit: int = 200
    ) -> list[dict]:
        """Outcome rows without a reaction whose delivery anchor closed the window.

        ``anchor`` = the turn's ``updated_at`` (delivery transition) falling
        back to ``created_at``. The C3 reaction job uses these to classify the
        VIP follow-up or record ``silence``.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=int(window_hours))
        anchor = func.coalesce(Turn.updated_at, Turn.created_at)
        stmt = (
            select(
                TurnOutcomeLog.turn_id,
                TurnOutcomeLog.vip_id,
                Turn.chat_id,
                anchor.label("anchor"),
            )
            .join(Turn, Turn.id == TurnOutcomeLog.turn_id)
            .where(
                TurnOutcomeLog.vip_signal.is_(None),
                anchor < cutoff,
            )
            .order_by(TurnOutcomeLog.created_at.desc())
            .limit(int(limit))
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [
                {
                    "turn_id": r.turn_id,
                    "vip_id": r.vip_id,
                    "chat_id": r.chat_id,
                    "anchor": r.anchor,
                }
                for r in result.all()
            ]

    async def purge_expired(self, ttl_days: int) -> int:
        """Delete outcome-log rows older than TTL, batched (purge-job pattern)."""
        batch_size = 1000
        cutoff = func.now() - text(":ttl_days * INTERVAL '1 day'")
        total_deleted = 0
        while True:
            async with self._sf() as session:
                batch_ids = (
                    select(TurnOutcomeLog.id)
                    .where(TurnOutcomeLog.created_at < cutoff)
                    .limit(batch_size)
                )
                stmt = (
                    TurnOutcomeLog.__table__.delete()
                    .where(TurnOutcomeLog.id.in_(batch_ids))
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
