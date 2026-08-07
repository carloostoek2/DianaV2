"""E2E: SqlVipProfileRepo.get_or_create + save_synthesis_result (atomic write).

The Fase 1 synthesis writer is the most critical repo of the cycle (A3 / A7):
one session + one commit that snapshots the PRIOR profile into
``vip_profile_history`` and upserts the new profile — the version bump and the
snapshot are never split by a crash. This suite verifies that invariant on
real Postgres, plus the JSONB serialization, the ``synthesis_trigger`` CHECK
and the ``vips`` FK (fix round S10).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from diana.application.ports import VipProfileRecord
from diana.infrastructure.db.models import VipProfile, VipProfileHistory
from diana.infrastructure.db.repositories.vip_profile import SqlVipProfileRepo


async def _create_vip(session_factory, telegram_user_id: int):
    from diana.infrastructure.db.repositories.vips import SqlVipStore

    vip_store = SqlVipStore(session_factory)
    return await vip_store.add(telegram_user_id, display_name="Synthesis VIP")


def _record(**kw) -> VipProfileRecord:
    data = dict(
        vip_id=uuid4(),
        stable_traits={"dedicada": True},
        recent_trend={"cercania": 0.8},
        sensitivities=[{"trait": "apertura", "weight": 0.6}],
        version=1,
        last_synthesized_at=datetime.now(UTC),
        synthesis_trigger=None,
    )
    data.update(kw)
    return VipProfileRecord(**data)


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_or_create_returns_existing_or_empty_default(session_factory):
    repo = SqlVipProfileRepo(session_factory)
    vip = await _create_vip(session_factory, 9401)

    # No row yet → read-only empty version-0 default, nothing written.
    created = await repo.get_or_create(vip.id)
    assert created.vip_id == vip.id
    assert created.version == 0
    assert created.stable_traits == {}
    assert created.sensitivities == []
    assert created.last_synthesized_at is None
    async with session_factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM vip_profile WHERE vip_id = :v"),
                {"v": vip.id},
            )
        ).scalar_one()
    assert count == 0  # get_or_create never writes

    # After a write, get_or_create returns the persisted row.
    nxt = _record(
        vip_id=vip.id, version=3, last_synthesized_at=datetime.now(UTC)
    )
    await repo.save_synthesis_result(
        vip.id, previous=None, next=nxt, changes_summary=None
    )
    existing = await repo.get_or_create(vip.id)
    assert existing.version == 3


@pytest.mark.db
@pytest.mark.asyncio
async def test_save_synthesis_result_previous_none_no_snapshot(session_factory):
    """A7: previous=None (first synthesis / low-confidence) → upsert only."""
    repo = SqlVipProfileRepo(session_factory)
    vip = await _create_vip(session_factory, 9402)
    now = datetime.now(UTC)
    nxt = _record(vip_id=vip.id, version=0, last_synthesized_at=now)

    saved = await repo.save_synthesis_result(
        vip.id, previous=None, next=nxt, changes_summary=None
    )
    assert saved.version == 0
    async with session_factory() as session:
        history_count = (
            await session.execute(
                text("SELECT count(*) FROM vip_profile_history WHERE vip_id = :v"),
                {"v": vip.id},
            )
        ).scalar_one()
    assert history_count == 0  # no snapshot without previous


@pytest.mark.db
@pytest.mark.asyncio
async def test_save_synthesis_result_snapshots_and_bumps_atomically(session_factory):
    """A3: previous + version+1 → history snapshot AND profile upsert land in
    the SAME commit (one session). The snapshot carries the PRIOR version."""
    repo = SqlVipProfileRepo(session_factory)
    vip = await _create_vip(session_factory, 9403)
    prev = _record(vip_id=vip.id, version=1, last_synthesized_at=datetime.now(UTC))
    await repo.save_synthesis_result(
        vip.id, previous=None, next=prev, changes_summary=None
    )

    now = datetime.now(UTC)
    nxt = _record(
        vip_id=vip.id,
        version=2,
        stable_traits={"dedicada": False, "nueva": True},
        recent_trend={"cercania": 0.9},
        sensitivities=[{"trait": "apertura", "weight": 0.8, "evidence_count": 1}],
        last_synthesized_at=now,
        synthesis_trigger="emotional_signal",
    )
    saved = await repo.save_synthesis_result(
        vip.id, previous=prev, next=nxt, changes_summary="más apertura"
    )
    assert saved.version == 2
    assert saved.stable_traits == {"dedicada": False, "nueva": True}

    async with session_factory() as session:
        profile = (
            await session.execute(
                select(VipProfile).where(VipProfile.vip_id == vip.id)
            )
        ).scalar_one()
        assert profile.version == 2
        assert profile.synthesis_trigger == "emotional_signal"
        assert profile.last_synthesized_at is not None

        history = (
            await session.execute(
                select(VipProfileHistory)
                .where(VipProfileHistory.vip_id == vip.id)
                .order_by(VipProfileHistory.created_at)
            )
        ).scalars().all()
        assert len(history) == 1
        snap = history[0]
        assert snap.version == 1  # snapshot carries the PRIOR version
        assert snap.diff_summary == "más apertura"
        # JSONB round-trip: the prior profile serialized as a dict, without
        # vip_id (model_dump exclude={"vip_id"}).
        assert "vip_id" not in snap.profile_snapshot
        assert snap.profile_snapshot["version"] == 1
        assert snap.profile_snapshot["stable_traits"] == {"dedicada": True}


@pytest.mark.db
@pytest.mark.asyncio
async def test_save_synthesis_result_jsonb_round_trips_lists(session_factory):
    """JSONB serialization of sensitivities/recent_trend (lists + nested dicts)."""
    repo = SqlVipProfileRepo(session_factory)
    vip = await _create_vip(session_factory, 9404)
    now = datetime.now(UTC)
    nxt = _record(
        vip_id=vip.id,
        version=1,
        stable_traits={"organizada": True, "detalles": {"plan": "viajar"}},
        recent_trend={"cercania": 0.75},
        sensitivities=[
            {"trait": "apertura", "weight": 0.6, "evidence_count": 0},
            {"trait": "familia", "weight": 0.9, "evidence_count": 3},
        ],
        last_synthesized_at=now,
        synthesis_trigger="volume",
    )
    await repo.save_synthesis_result(
        vip.id, previous=None, next=nxt, changes_summary="ok"
    )
    loaded = await repo.get_by_vip(vip.id)
    assert loaded is not None
    assert loaded.stable_traits == {"organizada": True, "detalles": {"plan": "viajar"}}
    assert loaded.sensitivities == [
        {"trait": "apertura", "weight": 0.6, "evidence_count": 0},
        {"trait": "familia", "weight": 0.9, "evidence_count": 3},
    ]
    assert loaded.recent_trend == {"cercania": 0.75}


@pytest.mark.db
@pytest.mark.asyncio
async def test_save_synthesis_result_check_synthesis_trigger(session_factory):
    """The CHECK ck_vip_profile_synthesis_trigger rejects out-of-vocab values.

    model_construct bypasses the pydantic Literal so the repo boundary (the
    real DB CHECK) is what must reject it.
    """
    repo = SqlVipProfileRepo(session_factory)
    vip = await _create_vip(session_factory, 9405)
    nxt = VipProfileRecord.model_construct(
        vip_id=vip.id,
        stable_traits={},
        recent_trend={},
        sensitivities=[],
        version=1,
        last_synthesized_at=datetime.now(UTC),
        synthesis_trigger="bogus",
    )
    with pytest.raises(IntegrityError):
        await repo.save_synthesis_result(
            vip.id, previous=None, next=nxt, changes_summary=None
        )
    # Nothing was persisted by the rejected write.
    assert await repo.get_by_vip(vip.id) is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_save_synthesis_result_unknown_vip_fails_fk(session_factory):
    """FK: writing a profile for a non-existent VIP violates vips.id."""
    repo = SqlVipProfileRepo(session_factory)
    ghost = uuid4()
    nxt = _record(vip_id=ghost, version=1)
    with pytest.raises(IntegrityError):
        await repo.save_synthesis_result(
            ghost, previous=None, next=nxt, changes_summary=None
        )
