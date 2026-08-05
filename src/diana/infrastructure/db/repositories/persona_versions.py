"""PersonaVersionRepo — versioned persona catalog snapshots (owner admin)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import PersonaAdminStore, PersonaVersionRecord
from diana.infrastructure.db.models import PersonaVersion


def persona_version_orm_to_record(row: PersonaVersion) -> PersonaVersionRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return PersonaVersionRecord(
        id=row.id,
        version=row.version,
        source=row.source,
        payload=row.payload,
        is_active=row.is_active,
        created_by=row.created_by,
        created_at=row.created_at,
        applied_at=row.applied_at,
        channel_type=row.channel_type,
    )


class PersonaVersionRepo:
    """Thin versioned-catalog persistence — no validation / feature flags.

    ``activate_version`` performs a single set-based UPDATE that flips exactly
    one row to ``is_active`` (and clears any previously active row) in the same
    statement, so the partial unique index ``uq_persona_versions_active`` is
    evaluated after the swap and never sees two active rows.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def insert_version(
        self,
        *,
        version: int,
        source: str,
        payload: dict[str, Any],
        created_by: int | None = None,
        channel_type: str = "vip",
    ) -> PersonaVersionRecord:
        """Insert a new inactive version row."""
        async with self._sf() as session:
            row = PersonaVersion(
                version=version,
                source=source,
                payload=payload,
                created_by=created_by,
                channel_type=channel_type,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return persona_version_orm_to_record(row)

    async def list_versions(
        self, *, channel_type: str | None = None
    ) -> list[PersonaVersionRecord]:
        """All versions for a channel (or all when channel_type is None),
        newest first (created_at DESC, version DESC)."""
        query = select(PersonaVersion)
        if channel_type is not None:
            query = query.where(PersonaVersion.channel_type == channel_type)
        async with self._sf() as session:
            result = await session.execute(
                query.order_by(
                    PersonaVersion.created_at.desc(),
                    PersonaVersion.version.desc(),
                )
            )
            return [
                persona_version_orm_to_record(row) for row in result.scalars()
            ]

    async def get_by_id(self, persona_version_id: UUID) -> PersonaVersionRecord | None:
        async with self._sf() as session:
            row = await session.get(PersonaVersion, persona_version_id)
            return persona_version_orm_to_record(row) if row is not None else None

    async def get_active(
        self, *, channel_type: str = "vip"
    ) -> PersonaVersionRecord | None:
        async with self._sf() as session:
            result = await session.execute(
                select(PersonaVersion).where(
                    PersonaVersion.is_active.is_(True),
                    PersonaVersion.channel_type == channel_type,
                )
            )
            row = result.scalar_one_or_none()
            return persona_version_orm_to_record(row) if row is not None else None

    async def activate_version(
        self,
        persona_version_id: UUID,
        *,
        now: datetime,
        channel_type: str = "vip",
    ) -> PersonaVersionRecord | None:
        """Activate *persona_version_id* and deactivate any other active row (atomic).

        Scoped to *channel_type*: a target id that does not exist (or belongs to
        another channel) is a no-op (returns None) — the swap only runs if the
        target row exists in this channel, so an unknown id never deactivates
        the currently active version. The partial unique index is evaluated
        after the statement, so the swap never observes two active rows.
        """
        exists = (
            select(PersonaVersion.id)
            .where(
                PersonaVersion.id == persona_version_id,
                PersonaVersion.channel_type == channel_type,
            )
            .exists()
        )
        async with self._sf() as session:
            await session.execute(
                update(PersonaVersion)
                .where(
                    or_(
                        (PersonaVersion.is_active.is_(True))
                        & (PersonaVersion.channel_type == channel_type),
                        PersonaVersion.id == persona_version_id,
                    )
                    & exists
                )
                .values(
                    is_active=PersonaVersion.id == persona_version_id,
                    applied_at=case(
                        (PersonaVersion.id == persona_version_id, now),
                        else_=PersonaVersion.applied_at,
                    ),
                )
            )
            await session.commit()
        record = await self.get_by_id(persona_version_id)
        # The UPDATE is channel-scoped; a cross-channel id matched zero rows,
        # so the re-fetch must verify the row actually belongs to this channel
        # before returning it (get_by_id itself is not channel-filtered).
        if record is None or record.channel_type != channel_type:
            return None
        return record


__all__ = ["PersonaVersionRepo", "persona_version_orm_to_record"]
