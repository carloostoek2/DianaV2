"""ProfilesRepo — VIP permanent profile by PK (BR-15 anti-contamination).

Content schema helpers live in ``diana.profile_content`` (shared pure module).
This module re-exports them and implements VIP-scoped SQL writers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from diana.infrastructure.db.models import Profile
from diana.profile_content import (
    apply_add_note,
    apply_delete_fact,
    apply_delete_note,
    apply_set_fact,
    empty_content,
    is_hollow_content,
    normalize_content,
)

_ZERO_EMBEDDING: list[float] = [0.0] * 384


def profile_to_dict(row: Profile) -> dict:
    """Convert a Profile ORM row to a plain dict for retriever consumption."""
    return {
        "vip_id": str(row.vip_id),
        "tipo": row.tipo,
        "content": row.content,
        "created_at": (
            row.created_at.isoformat()
            if hasattr(row.created_at, "isoformat")
            else str(row.created_at)
        ),
        "updated_at": (
            row.updated_at.isoformat()
            if hasattr(row.updated_at, "isoformat")
            else str(row.updated_at)
        ),
    }


class ProfilesRepo:
    """VIP permanent profile store (BR-15: every query filters by vip_id)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def _load(self, session: AsyncSession, vip_id: UUID) -> Profile | None:
        result = await session.execute(
            select(Profile).where(Profile.vip_id == vip_id)
        )
        return result.scalar_one_or_none()

    async def get_by_vip_id(self, vip_id: UUID) -> dict | None:
        """Return the profile row for ``vip_id``, or None if missing."""
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            return profile_to_dict(row) if row else None

    async def set_fact(self, vip_id: UUID, key: str, value: str) -> dict:
        """Upsert row if missing; set ``facts[key]=value``; return profile dict."""
        # Validate early so empty/oversize key/value never opens a DB session.
        content = apply_set_fact(empty_content(), key, value)
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                row = Profile(
                    vip_id=vip_id,
                    embedding=list(_ZERO_EMBEDDING),
                    content=content,
                    tipo="summary",
                )
                session.add(row)
            else:
                row.content = apply_set_fact(
                    normalize_content(row.content), key, value
                )
                flag_modified(row, "content")
            await session.commit()
            await session.refresh(row)
            return profile_to_dict(row)

    async def delete_fact(self, vip_id: UUID, key: str) -> dict | None:
        """Delete fact key. Missing row → None; missing key → current dict."""
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                return None
            new_content, _deleted = apply_delete_fact(
                normalize_content(row.content), key
            )
            row.content = new_content
            flag_modified(row, "content")
            await session.commit()
            await session.refresh(row)
            return profile_to_dict(row)

    async def add_note(
        self, vip_id: UUID, text: str, *, date: str | None = None
    ) -> dict:
        """Upsert shell if missing; append note; return profile dict."""
        note_date = (date or datetime.now(UTC).date().isoformat()).strip()
        content = apply_add_note(empty_content(), text, note_date)
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                row = Profile(
                    vip_id=vip_id,
                    embedding=list(_ZERO_EMBEDDING),
                    content=content,
                    tipo="summary",
                )
                session.add(row)
            else:
                row.content = apply_add_note(
                    normalize_content(row.content), text, note_date
                )
                flag_modified(row, "content")
            await session.commit()
            await session.refresh(row)
            return profile_to_dict(row)

    async def delete_note(self, vip_id: UUID, index: int) -> dict | None:
        """Delete note at 0-based index. Missing row or OOB → None."""
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                return None
            new_content, deleted = apply_delete_note(
                normalize_content(row.content), index
            )
            if not deleted:
                return None
            row.content = new_content
            flag_modified(row, "content")
            await session.commit()
            await session.refresh(row)
            return profile_to_dict(row)

    async def delete_by_vip_id(self, vip_id: UUID) -> bool:
        """DELETE profiles row for vip_id. True if deleted, False if none."""
        async with self._sf() as session:
            row = await self._load(session, vip_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


__all__ = [
    "ProfilesRepo",
    "apply_add_note",
    "apply_delete_fact",
    "apply_delete_note",
    "apply_set_fact",
    "empty_content",
    "is_hollow_content",
    "normalize_content",
    "profile_to_dict",
]
