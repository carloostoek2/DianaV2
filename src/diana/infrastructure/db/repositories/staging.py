"""StagingCandidateRepo — staging candidate CRUD (insert, get_by_id, update_status)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import StagingCandidate, Turn


class StagingCandidateRepo:
    """Staging candidate persistence for the controlled-learning pipeline.

    Supports:
    - insert: create a new pending candidate
    - get_by_id: lookup by UUID
    - list_pending: FIFO pending queue filtered by candidate_type
    - update_status: transition candidate status
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(
        self,
        candidate_type: str,
        payload: dict,
        turn_id: UUID,
    ) -> StagingCandidate:
        async with self._sf() as session:
            row = StagingCandidate(
                candidate_type=candidate_type,
                payload=payload,
                status="pending",
                turn_id=turn_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_by_id(self, candidate_id: UUID) -> StagingCandidate | None:
        async with self._sf() as session:
            return await session.get(StagingCandidate, candidate_id)

    async def list_pending(
        self,
        *,
        candidate_type: str = "example",
        limit: int = 10,
    ) -> list[StagingCandidate]:
        """Return pending candidates of the given type, oldest first (FIFO)."""
        async with self._sf() as session:
            result = await session.execute(
                select(StagingCandidate)
                .where(
                    StagingCandidate.status == "pending",
                    StagingCandidate.candidate_type == candidate_type,
                )
                .order_by(StagingCandidate.created_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def update_status(self, candidate_id: UUID, status: str) -> bool:
        """Set candidate status. Returns False if no row found."""
        async with self._sf() as session:
            result = await session.execute(
                update(StagingCandidate)
                .where(StagingCandidate.id == candidate_id)
                .values(status=status)
            )
            await session.commit()
            return result.rowcount > 0

    async def list_corrections_by_vip_since(
        self,
        vip_id: UUID,
        *,
        since: datetime | None,
        limit: int = 50,
    ) -> list[dict]:
        """Owner corrections of the VIP since ``since``, oldest first (A8 / EA-04).

        Fase 1 ``feedback_signals`` source: every ``candidate_type='example'``
        correction whose originating turn belongs to ``vip_id`` (the staging
        row itself does not store vip_id — the JOIN to ``turns.vip_id`` is
        required). The FULL payload is returned (``original_draft`` +
        ``corrected_text`` + ``context.turn_text``) so the synthesis LLM can
        separate tone/personality feedback from point content. Both ``pending``
        and promoted corrections are included (both are owner feedback). No
        index on ``staging_candidates.created_at`` → the query is bounded by
        ``limit`` (acceptable in shadow; documented).
        """
        stmt = (
            select(StagingCandidate)
            .join(Turn, Turn.id == StagingCandidate.turn_id)
            .where(
                Turn.vip_id == vip_id,
                StagingCandidate.candidate_type == "example",
            )
            .order_by(StagingCandidate.created_at.asc())
            .limit(limit)
        )
        if since is not None:
            stmt = stmt.where(StagingCandidate.created_at >= since)
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [
            {
                "created_at": (
                    r.created_at.isoformat()
                    if hasattr(r.created_at, "isoformat")
                    else str(r.created_at)
                ),
                "payload": r.payload,
                "status": r.status,
            }
            for r in rows
        ]


__all__ = ["StagingCandidateRepo"]
