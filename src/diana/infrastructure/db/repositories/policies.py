"""PoliciesRepo — active policy lookup by embedding similarity."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import Policy  # noqa: TCH001


def policy_to_dict(row: Policy) -> dict:
    """Convert a Policy ORM row to a plain dict for retriever consumption."""
    return {
        "id": str(row.id),
        "trigger_description": row.trigger_description,
        "rule": row.rule,
        "scope": row.scope,
        "is_active": row.is_active,
        "valid_until": row.valid_until.isoformat() if row.valid_until and hasattr(row.valid_until, "isoformat") else str(row.valid_until) if row.valid_until else None,
        "source_query_id": str(row.source_query_id) if row.source_query_id else None,
        "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
    }


class PoliciesRepo:
    """Active policy retriever filtered by scope and validity window."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(
        self,
        *,
        trigger_description: str,
        rule: str,
        scope: str = "all",
        is_active: bool = True,
        source_query_id: UUID | None = None,
        embedding: list[float] | None = None,
    ) -> Policy:
        async with self._sf() as session:
            row = Policy(
                embedding=embedding or [0.0] * 384,
                trigger_description=trigger_description,
                rule=rule,
                scope=scope,
                is_active=is_active,
                source_query_id=source_query_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def find_active_by_similarity(
        self,
        embedding: list[float],
        threshold: float = 0.8,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Find active policies whose embedding cosine similarity > ``threshold``.

        Filters by ``is_active = true`` and ``(valid_until IS NULL OR valid_until > now())``.
        When ``scope`` is provided, additionally filters by
        ``(scope = 'all' OR scope = :scope)``.
        """
        async with self._sf() as session:
            stmt = (
                select(Policy)
                .where(
                    Policy.is_active.is_(True),
                    (Policy.valid_until.is_(None)) | (Policy.valid_until > func.now()),
                    Policy.embedding.cosine_distance(embedding) < 1 - threshold,
                )
                .order_by(Policy.embedding.cosine_distance(embedding))
                .limit(limit)
            )
            if scope is not None:
                stmt = stmt.where((Policy.scope == "all") | (Policy.scope == scope))
            result = await session.execute(stmt)
            return [policy_to_dict(row) for row in result.scalars().all()]


__all__ = ["PoliciesRepo", "policy_to_dict"]
