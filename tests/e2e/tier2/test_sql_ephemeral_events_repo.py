"""E2E: EphemeralEventRepo.find_active_at window semantics against PostgreSQL.

Covers the production path ``find_active_at(now)``: only events that are
``not is_paused`` and within ``[start_at, end_at)`` are returned (half-open
window, start inclusive / end exclusive).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from diana.infrastructure.db.repositories.ephemeral_events import EphemeralEventRepo


@pytest.fixture(autouse=True)
async def _clean_ephemeral_events(session_factory):
    """Truncate ephemeral_events before/after each test.

    The table is global (no VIP FK) and the repo commits on write, so rows
    from one test leak into the next — unlike the VIP-scoped repos that
    isolate by distinct vip_id. Without this, ``find_active_at`` returns
    stale active events from earlier tests.
    """
    async with session_factory() as session:
        await session.execute(text("DELETE FROM ephemeral_events"))
        await session.commit()
    yield
    async with session_factory() as session:
        await session.execute(text("DELETE FROM ephemeral_events"))
        await session.commit()


@pytest.mark.db
@pytest.mark.asyncio
async def test_find_active_at_respects_paused_and_window(session_factory):
    """Only not-paused events with start_at <= now < end_at are returned."""
    repo = EphemeralEventRepo(session_factory)
    now = datetime.now(UTC)

    active = await repo.create(
        body="promo del fin de semana",
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(days=2),
    )
    paused = await repo.create(
        body="evento pausado",
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(days=2),
    )
    await repo.set_paused(paused.id, True)
    future = await repo.create(
        body="evento futuro",
        start_at=now + timedelta(days=1),
        end_at=now + timedelta(days=3),
    )
    expired = await repo.create(
        body="evento vencido",
        start_at=now - timedelta(days=3),
        end_at=now - timedelta(days=1),
    )

    ids = {r.id for r in await repo.find_active_at(now)}
    assert active.id in ids
    assert paused.id not in ids
    assert future.id not in ids
    assert expired.id not in ids


@pytest.mark.db
@pytest.mark.asyncio
async def test_find_active_at_window_is_half_open(session_factory):
    """start_at inclusive, end_at exclusive."""
    repo = EphemeralEventRepo(session_factory)
    base = datetime.now(UTC).replace(microsecond=0)
    ev = await repo.create(
        body="ventana",
        start_at=base,
        end_at=base + timedelta(seconds=5),
    )

    at_start = await repo.find_active_at(base)
    assert [r.id for r in at_start] == [ev.id]

    at_end = await repo.find_active_at(base + timedelta(seconds=5))
    assert at_end == []


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_open_returns_only_unterminated(session_factory):
    """list_open returns active + paused + future, excludes expired."""
    repo = EphemeralEventRepo(session_factory)
    now = datetime.now(UTC)

    active = await repo.create(
        body="a", start_at=now - timedelta(hours=1), end_at=now + timedelta(days=1)
    )
    paused = await repo.create(
        body="p", start_at=now - timedelta(hours=1), end_at=now + timedelta(days=1)
    )
    await repo.set_paused(paused.id, True)
    expired = await repo.create(
        body="x", start_at=now - timedelta(days=3), end_at=now - timedelta(days=1)
    )

    ids = {r.id for r in await repo.list_open(now)}
    assert active.id in ids
    assert paused.id in ids
    assert expired.id not in ids


@pytest.mark.db
@pytest.mark.asyncio
async def test_update_preserves_id_and_pause_state(session_factory):
    """update edits body/window in place, keeping id and is_paused."""
    repo = EphemeralEventRepo(session_factory)
    now = datetime.now(UTC)

    ev = await repo.create(
        body="original",
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(days=1),
    )
    await repo.set_paused(ev.id, True)

    updated = await repo.update(
        ev.id,
        body="editado",
        start_at=now,
        end_at=now + timedelta(days=3),
    )
    assert updated is not None
    assert updated.id == ev.id
    assert updated.body == "editado"
    assert updated.is_paused is True

    fetched = await repo.get(ev.id)
    assert fetched is not None
    assert fetched.body == "editado"
    assert fetched.is_paused is True
