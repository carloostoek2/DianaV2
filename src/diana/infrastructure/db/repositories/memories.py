"""MemoriesRepo — VIP-scoped embedding search (BR-15 anti-contamination)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import Memory


def memory_to_dict(row: Memory) -> dict:
    """Convert a Memory ORM row to a plain dict for retriever consumption."""
    return {
        "id": str(row.id),
        "vip_id": str(row.vip_id) if row.vip_id else None,
        "content": row.content,
        "category": row.category,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
    }


class MemoriesRepo:
    """VIP-scoped semantic memory store (BR-15: every query includes vip_id)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def find_by_vip_and_similarity(
        self,
        vip_id: UUID,
        embedding: list[float],
        threshold: float = 0.75,
        limit: int = 5,
    ) -> list[dict]:
        """Find memories for ``vip_id`` with cosine similarity > ``threshold``."""
        async with self._sf() as session:
            result = await session.execute(
                select(Memory)
                .where(
                    Memory.vip_id == vip_id,
                    Memory.embedding.cosine_distance(embedding) < 1 - threshold,
                )
                .order_by(Memory.embedding.cosine_distance(embedding))
                .limit(limit)
            )
            return [memory_to_dict(row) for row in result.scalars().all()]


__all__ = ["MemoriesRepo", "memory_to_dict"]
