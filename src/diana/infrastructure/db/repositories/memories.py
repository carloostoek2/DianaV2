"""MemoriesRepo — VIP-scoped embedding search (BR-15 anti-contamination)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import MemoryInsert
from diana.infrastructure.db.models import Memory

# F5-09: only facts the retriever may see (pending_owner/discarded never leak).
_VISIBLE_STATUSES = ("auto", "approved")
# Fix round (F6/L3/L7): the status vocabulary and the embedding dimension are
# enforced at the repo boundary — an out-of-domain value must fail loudly
# instead of silently becoming (in)visible to the retriever.
_VALID_STATUSES = ("auto", "pending_owner", "approved", "discarded")
_EMBEDDING_DIM = 384
# Fix round (F4): rows the owner already decided on survive regeneration.
# Only regenerable rows (auto/pending_owner) are replaced by a new backfill.
_REGENERABLE_STATUSES = ("auto", "pending_owner")


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
        The ``category='perfil'`` row is also excluded (fix round F1/M1): it is
        the full profile card for the owner's panel, not a retrievable fact —
        its JSON embeds every section (including sensitive ones).
        """
        async with self._sf() as session:
            result = await session.execute(
                select(Memory)
                .where(
                    Memory.vip_id == vip_id,
                    Memory.status.in_(_VISIBLE_STATUSES),
                    Memory.category != "perfil",
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
        """Idempotently replace the VIP's profile in one transaction.

        Fix round (F4, REQ-MEM-01/03): only the *regenerable* rows
        (``auto``/``pending_owner``) are deleted and reinserted. Rows the owner
        already decided on — ``approved`` and ``discarded`` — survive the
        regeneration; a new backfill never silently resets the approval state
        or drops an edited fact. The ``category='perfil'`` row (status
        ``auto``) is regenerable and gets replaced.

        Fix round (L7): the status vocabulary and the embedding dimension
        (384) are validated before touching the DB — out-of-domain values
        raise a descriptive ``ValueError`` instead of a raw DB error.

        Returns the total number of inserted rows (facts + perfil row).
        The perfil embedding is computed by the caller (service) — the repo
        never calls the embedder.
        """
        for r in rows:
            if r.status not in _VALID_STATUSES:
                raise ValueError(
                    f"invalid MemoryInsert.status {r.status!r}; "
                    f"expected one of {_VALID_STATUSES}"
                )
            if len(r.embedding) != _EMBEDDING_DIM:
                raise ValueError(
                    f"invalid embedding dimension {len(r.embedding)} for fact "
                    f"{r.text!r}; expected {_EMBEDDING_DIM}"
                )
        if len(perfil_embedding) != _EMBEDDING_DIM:
            raise ValueError(
                f"invalid perfil embedding dimension {len(perfil_embedding)}; "
                f"expected {_EMBEDDING_DIM}"
            )
        async with self._sf() as session:
            await session.execute(
                delete(Memory).where(
                    Memory.vip_id == vip_id,
                    Memory.status.in_(_REGENERABLE_STATUSES),
                )
            )
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


    async def has_profile(self, vip_id: UUID) -> bool:
        """True iff the VIP already has a ``perfil`` row (F5 Pool 2, F5-07).

        Powers ``enqueue_missing_vips``: VIPs that already have a profile are
        skipped. The ``category='perfil'`` row is written by
        ``replace_vip_profile`` on every successful finalize.

        Review L9 (by design): an EMPTY card (all facts semantically deduped,
        zero fact rows) still counts as "has profile" — that is the
        deliberate anti-loop guard. Without it, a VIP whose facts were all
        deduped against surviving rows would be re-enqueued at every startup
        and burn LLM calls for no new information. The on-demand path already
        avoids writing empty profiles (``empty_extraction`` report, no write).
        """
        async with self._sf() as session:
            result = await session.execute(
                select(
                    exists().where(
                        Memory.vip_id == vip_id,
                        Memory.category == "perfil",
                    )
                )
            )
            return bool(result.scalar_one())

    async def find_similar_surviving(
        self,
        vip_id: UUID,
        embedding: list[float],
        *,
        threshold: float = 0.85,
        category: str | None = None,
    ) -> list[dict]:
        """Find *surviving* memories of ``vip_id`` semantically close to ``embedding``.

        REQ-MEM-08 / F5-07 backfill dedup: only rows the owner already decided
        on — ``approved`` and ``discarded`` (fix F4 survivors) — are compared
        against; a new backfill may only *discard* a duplicate fact, never
        modify a surviving row (that would overwrite an owner decision). The
        ``perfil`` row is excluded (it is the panel card, not a fact).
        Returns up to 5 closest rows ordered by cosine distance, as plain
        dicts (``memory_to_dict``).
        """
        async with self._sf() as session:
            stmt = (
                select(Memory)
                .where(
                    Memory.vip_id == vip_id,
                    Memory.status.in_(("approved", "discarded")),
                    Memory.category != "perfil",
                    Memory.embedding.cosine_distance(embedding) < 1 - threshold,
                )
                .order_by(Memory.embedding.cosine_distance(embedding))
                .limit(5)
            )
            if category is not None:
                stmt = stmt.where(Memory.category == category)
            result = await session.execute(stmt)
            return [memory_to_dict(row) for row in result.scalars().all()]


__all__ = ["MemoriesRepo", "memory_to_dict"]
