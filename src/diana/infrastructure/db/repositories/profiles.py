"""ProfilesRepo — VIP permanent profile by PK (BR-15 anti-contamination).

Read-only residual: one row per VIP (PK ``vip_id``). No insert/update here.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.infrastructure.db.models import Profile


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

    async def get_by_vip_id(self, vip_id: UUID) -> dict | None:
        """Return the profile row for ``vip_id``, or None if missing."""
        async with self._sf() as session:
            result = await session.execute(
                select(Profile).where(Profile.vip_id == vip_id)
            )
            row = result.scalar_one_or_none()
            return profile_to_dict(row) if row else None


__all__ = ["ProfilesRepo", "profile_to_dict"]
