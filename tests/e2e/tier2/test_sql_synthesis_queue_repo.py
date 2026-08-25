"""E2E: SqlProfileSynthesisQueueRepo (Fila 4 C4) on real Postgres.

Verifies the durable pending upsert, the CAS drain (pending → processing), the
durable release and the stale-recovery reset. Requires Docker/testcontainers
(marker ``db``); skipped offline.
"""

from __future__ import annotations


import pytest
from sqlalchemy import text

from diana.infrastructure.db.repositories.synthesis_queue import (
    SqlProfileSynthesisQueueRepo,
)


async def _create_vip(session_factory, telegram_user_id: int):
    from diana.infrastructure.db.repositories.vips import SqlVipStore

    return await SqlVipStore(session_factory).add(
        telegram_user_id, display_name="Queue VIP"
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_upsert_pending_and_drain_claim(session_factory) -> None:
    repo = SqlProfileSynthesisQueueRepo(session_factory)
    vip = await _create_vip(session_factory, 9701)

    enqueued = await repo.upsert_pending(vip.id, "volume")
    assert enqueued.status == "pending"

    claimed = await repo.drain(limit=10)
    assert [c.vip_id for c in claimed] == [vip.id]
    assert claimed[0].status == "processing"
    assert claimed[0].started_at is not None
    await repo.complete(vip.id)  # keep the shared table clean for later tests


@pytest.mark.db
@pytest.mark.asyncio
async def test_complete_removes_row(session_factory) -> None:
    repo = SqlProfileSynthesisQueueRepo(session_factory)
    vip = await _create_vip(session_factory, 9702)

    await repo.upsert_pending(vip.id, "session_close")
    await repo.drain(limit=10)

    assert await repo.complete(vip.id) is True
    assert await repo.complete(vip.id) is False  # already gone


@pytest.mark.db
@pytest.mark.asyncio
async def test_recover_stale_resets_processing(session_factory) -> None:
    repo = SqlProfileSynthesisQueueRepo(session_factory)
    vip = await _create_vip(session_factory, 9703)

    await repo.upsert_pending(vip.id, "volume")
    claimed = await repo.drain(limit=10)
    assert claimed[0].status == "processing"

    # Age the row past the 1s window so recover_stale sees it as orphaned.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE profile_synthesis_queue "
                "SET updated_at = now() - interval '5 seconds' "
                "WHERE vip_id = :vip"
            ),
            {"vip": vip.id},
        )
        await session.commit()

    recovered = await repo.recover_stale(max_age_seconds=1)
    assert recovered == 1

    pending = await repo.list_pending(limit=10)
    assert [p.vip_id for p in pending] == [vip.id]
    assert pending[0].status == "pending"
    await repo.complete(vip.id)  # keep the shared table clean


@pytest.mark.db
@pytest.mark.asyncio
async def test_upsert_refreshes_trigger_not_status(session_factory) -> None:
    repo = SqlProfileSynthesisQueueRepo(session_factory)
    vip = await _create_vip(session_factory, 9704)

    await repo.upsert_pending(vip.id, "volume")
    await repo.drain(limit=10)  # → processing
    refreshed = await repo.upsert_pending(vip.id, "strong_signal")

    assert refreshed.status == "processing"  # never downgraded
    assert refreshed.trigger == "strong_signal"
    await repo.complete(vip.id)  # keep the shared table clean
