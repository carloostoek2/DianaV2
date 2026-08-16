"""ExamplesRepo — curated example lookup by embedding similarity.

Must never import from memory-related modules (AST gate enforcement).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import Example  # noqa: TCH001

VALID_EXAMPLE_QUALITIES = frozenset({"standard", "gold"})


def validate_example_quality(quality: str) -> str:
    if quality not in VALID_EXAMPLE_QUALITIES:
        raise ValueError("quality must be 'standard' or 'gold'")
    return quality


def vip_id_visibility_clause(column, vip_id: UUID | None):
    """Atención/None → IS NULL only. VIP → (IS NULL) OR (== vip_id)."""
    if vip_id is None:
        return column.is_(None)
    return (column.is_(None)) | (column == vip_id)


def example_similarity_order(embedding):
    return (
        case((Example.quality == "gold", 0), else_=1),
        Example.embedding.cosine_distance(embedding),
    )


def example_to_dict(row: Example) -> dict:
    """Convert an Example ORM row to a plain dict for retriever consumption."""
    return {
        "id": str(row.id),
        "turn_text": row.turn_text,
        "draft_text": row.draft_text,
        "corrected_text": row.corrected_text,
        "context": row.context,
        "is_counter_example": row.is_counter_example,
        "quality": row.quality,
        "vip_id": str(row.vip_id) if row.vip_id else None,
        "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
    }


class ExamplesRepo:
    """Curated example pool retriever (no VIP personal data)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(
        self,
        *,
        turn_text: str,
        draft_text: str,
        corrected_text: str,
        context: dict,
        is_counter_example: bool = False,
        embedding: list[float] | None = None,
        quality: str = "standard",
        vip_id: UUID | None = None,
    ) -> Example:
        quality = validate_example_quality(quality)
        async with self._sf() as session:
            row = Example(
                embedding=embedding or [0.0] * 384,
                turn_text=turn_text,
                draft_text=draft_text,
                corrected_text=corrected_text,
                context=context,
                is_counter_example=is_counter_example,
                quality=quality,
                vip_id=vip_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def find_by_similarity(
        self,
        embedding: list[float],
        threshold: float,
        limit: int = 5,
        counter_example: bool = False,
        vip_id: UUID | None = None,
    ) -> list[dict]:
        """Find examples with cosine similarity > ``threshold``.

        When ``counter_example`` is False, filters ``is_counter_example = false``.
        When ``counter_example`` is True, filters ``is_counter_example = true``.
        Gold rows over the threshold sort before more-similar standard rows.
        Atención (``vip_id is None``) sees only global rows.
        """
        async with self._sf() as session:
            result = await session.execute(
                select(Example)
                .where(
                    Example.is_counter_example.is_(counter_example),
                    Example.embedding.cosine_distance(embedding) < 1 - threshold,
                    vip_id_visibility_clause(Example.vip_id, vip_id),
                )
                .order_by(*example_similarity_order(embedding))
                .limit(limit)
            )
            return [example_to_dict(row) for row in result.scalars().all()]


__all__ = [
    "ExamplesRepo",
    "VALID_EXAMPLE_QUALITIES",
    "example_similarity_order",
    "example_to_dict",
    "validate_example_quality",
    "vip_id_visibility_clause",
]
