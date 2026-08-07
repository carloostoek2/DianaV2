"""VipProfileRepo — LLM-synthesized per-VIP profile (Fase 1 writer).

DISTINTO de ``profiles`` (tabla vector, ``repositories/memories.py``) y de
``/vip_profile`` (comando legacy admin). Fase 0 = schema-only; Fase 1 =
``get_or_create`` (read-only default) + ``save_synthesis_result`` (atomic
snapshot + upsert).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import VipProfileRecord
from diana.infrastructure.db.models import VipProfile, VipProfileHistory


def vip_profile_orm_to_record(row: VipProfile) -> VipProfileRecord:
    """Pure mapper ORM → record (unit-testable without DB)."""
    return VipProfileRecord(
        vip_id=row.vip_id,
        stable_traits=dict(row.stable_traits),
        recent_trend=dict(row.recent_trend),
        sensitivities=list(row.sensitivities),
        version=row.version,
        last_synthesized_at=row.last_synthesized_at,
        synthesis_trigger=row.synthesis_trigger,
    )


class SqlVipProfileRepo:
    """Thin persistence for the synthesized profile — no synthesis logic.

    ``insert`` is a simple upsert keyed on ``vip_id`` (Postgres ON CONFLICT):
    it overwrites the mutable columns with the caller's record values verbatim.
    ``save_synthesis_result`` is the Fase 1 atomic writer: it snapshots the
    PRIOR profile into ``vip_profile_history`` and upserts the new profile in
    ONE session/commit, so the version bump and the snapshot are never split
    by a crash. ``get_or_create`` is read-only (never writes the version-0
    default — the service decides whether the snapshot applies, A7).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_by_vip(self, vip_id: Any) -> VipProfileRecord | None:
        async with self._sf() as session:
            row = await session.get(VipProfile, vip_id)
            return vip_profile_orm_to_record(row) if row is not None else None

    async def get_or_create(self, vip_id: Any) -> VipProfileRecord:
        """Return the existing profile or an empty version-0 default (read-only; no write)."""
        row = await self.get_by_vip(vip_id)
        if row is not None:
            return row
        return VipProfileRecord(
            vip_id=vip_id,
            stable_traits={},
            recent_trend={},
            sensitivities=[],
            version=0,
            last_synthesized_at=None,
            synthesis_trigger=None,
        )

    async def save_synthesis_result(
        self,
        vip_id: Any,
        *,
        previous: VipProfileRecord | None,
        next: VipProfileRecord,
        changes_summary: str | None,
    ) -> VipProfileRecord:
        """Atomic write of one synthesis result (history snapshot + profile upsert).

        One session + one commit: the history snapshot of the PRIOR profile
        (``previous``) is inserted FIRST, then the profile is upserted with
        ``next``'s fields (ON CONFLICT DO UPDATE keyed on vip_id). ``previous``
        None → no snapshot (first synthesis, low-confidence branch). The
        in-memory guard (A3) prevents a version race between same-process
        workers.
        """
        stmt = (
            insert(VipProfile)
            .values(
                vip_id=next.vip_id,
                stable_traits=next.stable_traits,
                recent_trend=next.recent_trend,
                sensitivities=next.sensitivities,
                version=next.version,
                last_synthesized_at=next.last_synthesized_at,
                synthesis_trigger=next.synthesis_trigger,
            )
            .on_conflict_do_update(
                index_elements=[VipProfile.vip_id],
                set_={
                    "stable_traits": next.stable_traits,
                    "recent_trend": next.recent_trend,
                    "sensitivities": next.sensitivities,
                    "version": next.version,
                    "last_synthesized_at": next.last_synthesized_at,
                    "synthesis_trigger": next.synthesis_trigger,
                },
            )
            .returning(VipProfile)
        )
        async with self._sf() as session:
            if previous is not None:
                session.add(
                    VipProfileHistory(
                        vip_id=vip_id,
                        version=previous.version,
                        profile_snapshot=previous.model_dump(
                            mode="json", exclude={"vip_id"}
                        ),
                        diff_summary=changes_summary,
                    )
                )
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalar_one()
            return vip_profile_orm_to_record(row)

    async def insert(self, record: VipProfileRecord) -> VipProfileRecord:
        stmt = (
            insert(VipProfile)
            .values(
                vip_id=record.vip_id,
                stable_traits=record.stable_traits,
                recent_trend=record.recent_trend,
                sensitivities=record.sensitivities,
                version=record.version,
                last_synthesized_at=record.last_synthesized_at,
                synthesis_trigger=record.synthesis_trigger,
            )
            .on_conflict_do_update(
                index_elements=[VipProfile.vip_id],
                set_={
                    "stable_traits": record.stable_traits,
                    "recent_trend": record.recent_trend,
                    "sensitivities": record.sensitivities,
                    "version": record.version,
                    "last_synthesized_at": record.last_synthesized_at,
                    "synthesis_trigger": record.synthesis_trigger,
                },
            )
            .returning(VipProfile)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalar_one()
            return vip_profile_orm_to_record(row)


__all__ = ["SqlVipProfileRepo", "vip_profile_orm_to_record"]
