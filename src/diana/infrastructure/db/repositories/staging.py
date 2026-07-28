"""StagingCandidateRepo — staging candidate CRUD (insert, get_by_id, update_status)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import StagingCandidate


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


__all__ = ["StagingCandidateRepo"]
