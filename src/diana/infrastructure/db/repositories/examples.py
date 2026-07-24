"""ExamplesRepo — curated example lookup by embedding similarity.

Must never import from memory-related modules (AST gate enforcement).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import Example


def example_to_dict(row: Example) -> dict:
    """Convert an Example ORM row to a plain dict for retriever consumption."""
    return {
        "id": str(row.id),
        "turn_text": row.turn_text,
        "draft_text": row.draft_text,
        "corrected_text": row.corrected_text,
        "context": row.context,
        "is_counter_example": row.is_counter_example,
        "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
    }


class ExamplesRepo:
    """Curated example pool retriever (no VIP personal data)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def find_by_similarity(
        self,
        embedding: list[float],
        threshold: float,
        limit: int = 5,
        counter_example: bool = False,
    ) -> list[dict]:
        """Find examples with cosine similarity > ``threshold``.

        When ``counter_example`` is False, filters ``is_counter_example = false``.
        When ``counter_example`` is True, filters ``is_counter_example = true``.
        """
        async with self._sf() as session:
            result = await session.execute(
                select(Example)
                .where(
                    Example.is_counter_example.is_(counter_example),
                    Example.embedding.cosine_distance(embedding) < 1 - threshold,
                )
                .order_by(Example.embedding.cosine_distance(embedding))
                .limit(limit)
            )
            return [example_to_dict(row) for row in result.scalars().all()]


__all__ = ["ExamplesRepo", "example_to_dict"]
