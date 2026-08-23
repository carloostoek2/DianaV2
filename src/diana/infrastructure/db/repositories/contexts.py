"""ContextsRepo — interpreted temporal context store (REQ-MEM-06).

The `contexts` table was designed in F2 (migration 003) as the home of
*interpreted* temporal facts — distinct from raw history (REQ-MEM-06):
the History retriever returns messages; the Context retriever returns
already-interpreted temporal facts with an expiry. This repo implements the
design that was left unwired: write interpreted snapshots (post-turn) with an
embedding and an expiry, and read back only the non-expired ones.

No business logic here (AGENTS.md): the caller decides what to interpret.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import Context


def context_to_dict(row: Context) -> dict:
    """Convert a Context ORM row to a plain dict for retriever consumption."""
    return {
        "id": str(row.id),
        "vip_id": str(row.vip_id) if row.vip_id else None,
        "chat_id": row.chat_id,
        "content": row.content,
        "expires_at": (
            row.expires_at.isoformat()
            if hasattr(row.expires_at, "isoformat")
            else str(row.expires_at)
        ),
        "created_at": (
            row.created_at.isoformat()
            if hasattr(row.created_at, "isoformat")
            else str(row.created_at)
        ),
    }


class ContextsRepo:
    """Persist and read interpreted temporal context snapshots (expiry-gated)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert(
        self,
        *,
        chat_id: int,
        content: dict[str, Any],
        embedding: list[float],
        expires_at: datetime,
        vip_id: UUID | None = None,
    ) -> dict:
        """Insert one interpreted context snapshot with embedding and expiry."""
        row = Context(
            vip_id=vip_id,
            chat_id=chat_id,
            embedding=embedding,
            content=content,
            expires_at=expires_at,
        )
        async with self._sf() as session:
            # Opportunistic cleanup: drop this chat's expired snapshots while
            # we are here (cheap, keeps the table bounded without a job).
            from sqlalchemy import delete

            await session.execute(
                delete(Context).where(
                    Context.chat_id == chat_id,
                    Context.expires_at <= datetime.now(UTC),
                )
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return context_to_dict(row)

    async def find_active_by_chat(
        self,
        chat_id: int,
        *,
        vip_id: UUID | None = None,
        limit: int = 20,
        now: datetime | None = None,
    ) -> list[dict]:
        """Return non-expired interpreted snapshots for ``chat_id`` (recent first)."""
        now = now or datetime.now(UTC)
        stmt = (
            select(Context)
            .where(Context.chat_id == chat_id, Context.expires_at > now)
            .order_by(Context.created_at.desc())
            .limit(limit)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [context_to_dict(row) for row in result.scalars().all()]

    async def find_by_similarity(
        self,
        embedding: list[float],
        *,
        threshold: float,
        limit: int = 5,
        chat_id: int | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        """Return non-expired snapshots semantically close to ``embedding``.

        ``chat_id`` optional scope (default: all chats). Cosine similarity
        > ``threshold`` → cosine distance < ``1 - threshold``.
        """
        now = now or datetime.now(UTC)
        stmt = select(Context).where(Context.expires_at > now)
        if chat_id is not None:
            stmt = stmt.where(Context.chat_id == chat_id)
        stmt = (
            stmt.where(Context.embedding.cosine_distance(embedding) < 1 - threshold)
            .order_by(Context.embedding.cosine_distance(embedding))
            .limit(limit)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [context_to_dict(row) for row in result.scalars().all()]

    async def delete_expired(self, now: datetime | None = None) -> int:
        """Purge expired snapshots; returns deleted row count."""
        from sqlalchemy import delete

        now = now or datetime.now(UTC)
        async with self._sf() as session:
            result = await session.execute(
                delete(Context).where(Context.expires_at <= now)
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def purge_expired(self, ttl_days: int = 1) -> int:
        """AgentDataPurgeJob-compatible hook — expiry is row-level (expires_at),
        so TTL days are ignored; only truly expired rows are deleted."""
        return await self.delete_expired()


__all__ = ["ContextsRepo", "context_to_dict"]
