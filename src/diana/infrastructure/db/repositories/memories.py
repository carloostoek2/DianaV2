"""MemoriesRepo — VIP-scoped embedding search (BR-15 anti-contamination)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import MemoryInsert
from diana.infrastructure.db.models import Memory

# F5-09: only facts the retriever may see (pending_owner/discarded never leak).
_VISIBLE_STATUSES = ("auto", "approved")


def memory_to_dict(row: Memory) -> dict:
    """Convert a Memory ORM row to a plain dict for retriever consumption."""
    return {
        "id": str(row.id),
        "vip_id": str(row.vip_id) if row.vip_id else None,
        "content": row.content,
        "category": row.category,
        "confidence": row.confidence,
        "status": row.status,
        "source_turn_id": str(row.source_turn_id) if row.source_turn_id else None,
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
        """Find visible memories for ``vip_id`` with cosine similarity > ``threshold``.

        Visibility filter (F5-09, REQ-MEM-10/11): only ``auto``/``approved``
        rows reach the retriever; ``pending_owner``/``discarded`` never do.
        """
        async with self._sf() as session:
            result = await session.execute(
                select(Memory)
                .where(
                    Memory.vip_id == vip_id,
                    Memory.status.in_(_VISIBLE_STATUSES),
                    Memory.embedding.cosine_distance(embedding) < 1 - threshold,
                )
                .order_by(Memory.embedding.cosine_distance(embedding))
                .limit(limit)
            )
            return [memory_to_dict(row) for row in result.scalars().all()]

    async def replace_vip_profile(
        self,
        vip_id: UUID,
        *,
        rows: list[MemoryInsert],
        perfil: dict,
        perfil_embedding: list[float],
    ) -> int:
        """Idempotently replace the VIP's whole profile in one transaction.

        Deletes every existing ``memories`` row for ``vip_id`` and inserts the
        section facts (``content`` with canonical ``texto`` + ``fact`` mirror)
        plus the ``category='perfil'`` row (REQ-MEM-03). Returns the total
        number of inserted rows. Never duplicates: regeneration replaces.
        The perfil embedding is computed by the caller (service) — the repo
        never calls the embedder.
        """
        async with self._sf() as session:
            await session.execute(delete(Memory).where(Memory.vip_id == vip_id))
            for r in rows:
                session.add(
                    Memory(
                        vip_id=vip_id,
                        embedding=r.embedding,
                        content={
                            "texto": r.text,
                            "tipo": "hecho",
                            "confianza": r.confidence,
                            "fuente": "backfill",
                            "turno_id": None,
                            "aprobado_por": r.approved_by,
                            "fact": r.text,
                        },
                        category=r.category,
                        confidence=r.confidence,
                        status=r.status,
                        source_turn_id=r.source_turn_id,
                    )
                )
            session.add(
                Memory(
                    vip_id=vip_id,
                    embedding=perfil_embedding,
                    content=perfil,
                    category="perfil",
                    confidence=1.0,
                    status="auto",
                    source_turn_id=None,
                )
            )
            await session.commit()
        return len(rows) + 1


__all__ = ["MemoriesRepo", "memory_to_dict"]
