"""SqlBackfillQueueRepo — durable per-VIP backfill queue (REQ-MEM-05, F5 Pool 2).

Infrastructure repository over ``backfill_queue`` (migration 023). Claim of
the next job is atomic: ``FOR UPDATE SKIP LOCKED`` inside the pop transaction
guarantees a single worker (or a future multi-worker deployment) never grabs
the same job twice. The partial unique index ``uq_backfill_queue_active_vip``
(pending/processing only) makes ``enqueue`` idempotent per VIP.

The window-by-window re-enqueue is expressed as ``save_progress``: the job
returns to ``pending`` with an advanced ``window_index``, so the same VIP
becomes FIFO-eligible again on the next cycle (the scheduler spaces units
with ``backfill_interval_sec``).

No business logic here (AGENTS.md §2.1) — the queue service lives in
``application/memory_backfill_queue.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import BackfillJobRecord
from diana.infrastructure.db.models import BackfillQueue

logger = logging.getLogger("diana.infrastructure")


def _to_record(row: BackfillQueue) -> BackfillJobRecord:
    """Map an ORM row to the application DTO (jsonb state → dict)."""
    return BackfillJobRecord(
        id=row.id,
        vip_id=row.vip_id,
        chat_id=row.chat_id,
        status=row.status,
        window_index=row.window_index,
        state=dict(row.state or {}),
        attempts=row.attempts,
        last_error=row.last_error,
        outcome=row.outcome,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlBackfillQueueRepo:
    """Postgres-backed ``BackfillQueueStore`` (structural typing)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def enqueue(self, vip_id: UUID, chat_id: int) -> BackfillJobRecord | None:
        """Insert a new ``pending`` job; None if one is already active.

        The partial unique index on active rows turns a duplicate insert into
        an IntegrityError, which is caught and rolled back here — the caller
        sees ``None`` (already queued) instead of a raw DB error.
        """
        async with self._sf() as session:
            row = BackfillQueue(
                vip_id=vip_id,
                chat_id=chat_id,
                status="pending",
                window_index=0,
                state={},
                attempts=0,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
            await session.refresh(row)
            return _to_record(row)

    async def pop_pending(self) -> BackfillJobRecord | None:
        """Atomically claim the oldest pending job (FIFO) → ``processing``."""
        async with self._sf() as session:
            result = await session.execute(
                select(BackfillQueue)
                .where(BackfillQueue.status == "pending")
                .order_by(BackfillQueue.created_at.asc(), BackfillQueue.id.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = result.scalars().first()
            if row is None:
                return None
            row.status = "processing"
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return _to_record(row)

    async def save_progress(
        self,
        job_id: UUID,
        *,
        window_index: int,
        state: dict[str, Any],
        attempts: int,
    ) -> None:
        """Persist progress and return the job to ``pending`` (re-enqueue).

        ``pending`` + advanced ``window_index`` makes the same VIP eligible
        again on the next cycle — this IS the per-window re-enqueue.
        """
        async with self._sf() as session:
            await session.execute(
                update(BackfillQueue)
                .where(BackfillQueue.id == job_id)
                .values(
                    status="pending",
                    window_index=window_index,
                    state=state,
                    attempts=attempts,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def mark_done(self, job_id: UUID, *, outcome: str) -> None:
        async with self._sf() as session:
            await session.execute(
                update(BackfillQueue)
                .where(BackfillQueue.id == job_id)
                .values(status="done", outcome=outcome, updated_at=datetime.now(UTC))
            )
            await session.commit()

    async def mark_failed(self, job_id: UUID, *, error: str) -> None:
        async with self._sf() as session:
            await session.execute(
                update(BackfillQueue)
                .where(BackfillQueue.id == job_id)
                .values(
                    status="failed",
                    last_error=error,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def requeue(
        self, job_id: UUID, *, attempts: int, error: str | None = None
    ) -> None:
        async with self._sf() as session:
            await session.execute(
                update(BackfillQueue)
                .where(BackfillQueue.id == job_id)
                .values(
                    status="pending",
                    attempts=attempts,
                    last_error=error,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def recover_stale(self) -> int:
        """Requeue every orphaned ``processing`` job (crash recovery)."""
        async with self._sf() as session:
            result = await session.execute(
                update(BackfillQueue)
                .where(BackfillQueue.status == "processing")
                .values(status="pending", updated_at=datetime.now(UTC))
            )
            await session.commit()
            return result.rowcount or 0

    async def has_recent_empty_done(
        self, vip_id: UUID, *, since: datetime
    ) -> bool:
        """True iff the VIP was marked ``done(empty_history)`` after ``since``.

        Powers the 24h guard in ``enqueue_missing_vips`` (no re-enqueue loop
        for VIPs whose seed is still pending).
        """
        async with self._sf() as session:
            result = await session.execute(
                select(
                    exists().where(
                        BackfillQueue.vip_id == vip_id,
                        BackfillQueue.status == "done",
                        BackfillQueue.outcome == "empty_history",
                        BackfillQueue.updated_at >= since,
                    )
                )
            )
            return bool(result.scalar_one())


__all__ = ["SqlBackfillQueueRepo"]
