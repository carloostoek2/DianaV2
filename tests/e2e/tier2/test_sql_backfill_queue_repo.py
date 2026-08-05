"""E2E: SqlBackfillQueueRepo against real Postgres (REQ-MEM-05, F5 Pool 2).

Covers the full queue lifecycle: idempotent enqueue (partial unique index),
atomic FIFO pop with ``SKIP LOCKED``, per-window ``save_progress`` re-enqueue,
mark_done/mark_failed/requeue, crash recovery (``recover_stale``), the 24h
``empty_history`` guard, and regeneration after a ``done`` job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text, update

from diana.infrastructure.db.models import BackfillQueue
from diana.infrastructure.db.repositories.backfill_queue import (
    SqlBackfillQueueRepo,
)


@pytest.fixture(autouse=True)
async def _clean_backfill_queue(session_factory):
    """Isolate each test: the shared session DB accumulates queue rows across
    tests (they commit by design), which would break FIFO pops and
    ``recover_stale`` counts."""
    async with session_factory() as session:
        await session.execute(text("DELETE FROM backfill_queue"))
        await session.commit()
    yield


async def _create_vip(session_factory, telegram_user_id: int):
    async with session_factory() as session:
        vip_id = (
            await session.execute(
                text(
                    "INSERT INTO vips (telegram_user_id) "
                    "VALUES (:t) RETURNING id"
                ),
                {"t": telegram_user_id},
            )
        ).scalar_one()
        await session.commit()
        return vip_id


async def _get_row(session_factory, job_id):
    async with session_factory() as session:
        return (
            await session.execute(
                text(
                    "SELECT status, window_index, state, attempts, "
                    "       last_error, outcome "
                    "FROM backfill_queue WHERE id = :jid"
                ),
                {"jid": job_id},
            )
        ).mappings().first()


@pytest.mark.db
@pytest.mark.asyncio
async def test_enqueue_and_dup_returns_none(session_factory) -> None:
    repo = SqlBackfillQueueRepo(session_factory)
    vip_a = await _create_vip(session_factory, 601)
    vip_b = await _create_vip(session_factory, 602)

    rec = await repo.enqueue(vip_a, chat_id=601)
    assert rec is not None
    assert rec.status == "pending"
    assert rec.window_index == 0
    assert rec.state == {}

    # Same VIP while pending → None (partial unique index).
    assert await repo.enqueue(vip_a, chat_id=601) is None

    # Different VIP → OK.
    rec_b = await repo.enqueue(vip_b, chat_id=602)
    assert rec_b is not None and rec_b.vip_id == vip_b


@pytest.mark.db
@pytest.mark.asyncio
async def test_pop_pending_fifo_and_processing(session_factory) -> None:
    repo = SqlBackfillQueueRepo(session_factory)
    vip_a = await _create_vip(session_factory, 603)
    vip_b = await _create_vip(session_factory, 604)
    job_a = await repo.enqueue(vip_a, chat_id=603)
    assert job_a is not None
    # Make FIFO deterministic: force job_a strictly older than job_b (two
    # back-to-back commits can land on the same ``now()`` microsecond).
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE backfill_queue SET created_at = now() - interval '1 second' "
                "WHERE id = :jid"
            ),
            {"jid": job_a.id},
        )
        await session.commit()
    job_b = await repo.enqueue(vip_b, chat_id=604)
    assert job_b is not None

    first = await repo.pop_pending()
    assert first is not None and first.id == job_a.id  # FIFO by created_at
    assert first.status == "processing"

    second = await repo.pop_pending()
    assert second is not None and second.id == job_b.id
    assert second.status == "processing"

    assert await repo.pop_pending() is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_pop_pending_skips_processing(session_factory) -> None:
    repo = SqlBackfillQueueRepo(session_factory)
    vip_a = await _create_vip(session_factory, 605)
    vip_b = await _create_vip(session_factory, 606)
    job_a = await repo.enqueue(vip_a, chat_id=605)
    assert job_a is not None
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE backfill_queue SET created_at = now() - interval '1 second' "
                "WHERE id = :jid"
            ),
            {"jid": job_a.id},
        )
        await session.commit()
    await repo.enqueue(vip_b, chat_id=606)

    claimed = await repo.pop_pending()
    assert claimed is not None and claimed.id == job_a.id

    # The processing job (A) is not returned again; B comes next.
    second = await repo.pop_pending()
    assert second is not None and second.vip_id == vip_b


@pytest.mark.db
@pytest.mark.asyncio
async def test_save_progress_requeues_window(session_factory) -> None:
    repo = SqlBackfillQueueRepo(session_factory)
    vip_a = await _create_vip(session_factory, 607)
    job = await repo.enqueue(vip_a, chat_id=607)
    assert job is not None

    claimed = await repo.pop_pending()
    assert claimed is not None
    await repo.save_progress(
        job.id, window_index=1, state={"hechos": []}, attempts=0
    )

    row = await _get_row(session_factory, job.id)
    assert row["status"] == "pending"
    assert row["window_index"] == 1

    # The same VIP is eligible again on the next cycle.
    again = await repo.pop_pending()
    assert again is not None and again.id == job.id
    assert again.window_index == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_requeue_and_failed_and_done(session_factory) -> None:
    repo = SqlBackfillQueueRepo(session_factory)
    vip_a = await _create_vip(session_factory, 608)
    job = await repo.enqueue(vip_a, chat_id=608)
    assert job is not None

    await repo.requeue(job.id, attempts=2, error="x")
    row = await _get_row(session_factory, job.id)
    assert row["status"] == "pending"
    assert row["attempts"] == 2
    assert row["last_error"] == "x"

    await repo.mark_failed(job.id, error="window_llm_failed")
    row = await _get_row(session_factory, job.id)
    assert row["status"] == "failed"
    assert row["last_error"] == "window_llm_failed"

    # failed is not active → a fresh enqueue works, then mark done.
    job2 = await repo.enqueue(vip_a, chat_id=608)
    assert job2 is not None
    await repo.mark_done(job2.id, outcome="ok")
    row = await _get_row(session_factory, job2.id)
    assert row["status"] == "done"
    assert row["outcome"] == "ok"


@pytest.mark.db
@pytest.mark.asyncio
async def test_recover_stale_requeues_processing(session_factory) -> None:
    repo = SqlBackfillQueueRepo(session_factory)
    vip_a = await _create_vip(session_factory, 609)
    job = await repo.enqueue(vip_a, chat_id=609)
    assert job is not None
    await repo.pop_pending()  # leaves the job processing

    # A fresh processing job must NOT be reclaimed (age limit, fix round):
    # an overlapping restart could still be extracting that window.
    recovered = await repo.recover_stale()
    assert recovered == 0

    # Age the job beyond the default 1h limit → now it is an orphan.
    async with session_factory() as session:
        await session.execute(
            update(BackfillQueue)
            .where(BackfillQueue.id == job.id)
            .values(updated_at=datetime.now(UTC) - timedelta(hours=2))
        )
        await session.commit()

    recovered = await repo.recover_stale()
    assert recovered == 1

    again = await repo.pop_pending()
    assert again is not None and again.id == job.id
    # The second pop claimed it again → the job is processing once more.
    row = await _get_row(session_factory, job.id)
    assert row["status"] == "processing"


@pytest.mark.db
@pytest.mark.asyncio
async def test_has_recent_empty_done(session_factory) -> None:
    repo = SqlBackfillQueueRepo(session_factory)
    vip_a = await _create_vip(session_factory, 610)
    job = await repo.enqueue(vip_a, chat_id=610)
    assert job is not None
    await repo.mark_done(job.id, outcome="empty_history")

    now = datetime.now(UTC)
    assert await repo.has_recent_empty_done(vip_a, since=now - timedelta(hours=1))
    assert not await repo.has_recent_empty_done(vip_a, since=now + timedelta(hours=1))

    # A done with outcome='ok' does not satisfy the guard.
    vip_b = await _create_vip(session_factory, 611)
    job_b = await repo.enqueue(vip_b, chat_id=611)
    assert job_b is not None
    await repo.mark_done(job_b.id, outcome="ok")
    assert not await repo.has_recent_empty_done(vip_b, since=now - timedelta(hours=1))


@pytest.mark.db
@pytest.mark.asyncio
async def test_done_job_does_not_block_reenqueue(session_factory) -> None:
    repo = SqlBackfillQueueRepo(session_factory)
    vip_a = await _create_vip(session_factory, 612)
    job = await repo.enqueue(vip_a, chat_id=612)
    assert job is not None
    await repo.mark_done(job.id, outcome="ok")

    # Regeneration: a done job does not block a new enqueue for the same VIP.
    job2 = await repo.enqueue(vip_a, chat_id=612)
    assert job2 is not None
    assert job2.id != job.id
