"""MemoryBackfillQueue — durable per-VIP backfill queue service (REQ-MEM-05, F5 Pool 2).

Application service (AGENTS.md §2.1) sitting between the ``SqlBackfillQueueRepo``
(Postgres, migration 023) and the ``MemoryBackfillService`` (window-by-window
extraction). It owns:

- Idempotent enqueue per VIP (the store's partial unique index on active rows
  makes a duplicate insert return ``None`` → ``already_pending``).
- ``schedule_enqueue`` fire-and-forget (pattern ``VipHistorySeedService``):
  the ficha button never blocks the panel; the owner gets a best-effort DM
  with the estimated step count ("~N pasos", one window per step).
- ``enqueue_missing_vips``: active VIPs with history and no profile (24h guard
  for ``done(empty_history)``) are queued at startup / on demand — never
  during the turn pipeline.
- ``process_one``: ONE transcript window per cycle. The job pops a pending job,
  extracts ``window_index``, and either ``save_progress`` (re-enqueue the same
  VIP for its next window — the scheduler spaces units with
  ``backfill_interval_sec``) or ``finalize_profile`` + ``mark_done``. LLM
  window failures retry up to ``max_attempts`` (respecting the interval),
  then ``failed``. ``done(empty_history)`` covers empty history / empty
  transcript with no write.

Purity: imports only stdlib + application modules (no telegram/behavior/
infrastructure sessions — the store is a local Protocol).
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from diana.application.memory_backfill_service import (
    HechoExtracted,
    HistoryReader,
    MemoryBackfillService,
    WindowExtractionResult,
)
from diana.application.ports import BackfillJobRecord, OwnerNotifierPort, VipRecord

logger = logging.getLogger("diana.application")

__all__ = [
    "BackfillQueueStore",
    "EnqueueReport",
    "MemoryBackfillQueue",
    "ProcessReport",
]


class BackfillQueueStore(Protocol):
    """Persistent backfill queue (implemented by ``SqlBackfillQueueRepo``)."""

    async def enqueue(self, vip_id: UUID, chat_id: int) -> BackfillJobRecord | None: ...

    async def pop_pending(self) -> BackfillJobRecord | None: ...

    async def save_progress(
        self, job_id: UUID, *, window_index: int, state: dict, attempts: int
    ) -> None: ...

    async def mark_done(self, job_id: UUID, *, outcome: str) -> None: ...

    async def mark_failed(self, job_id: UUID, *, error: str) -> None: ...

    async def requeue(
        self, job_id: UUID, *, attempts: int, error: str | None = None
    ) -> None: ...

    async def recover_stale(self, *, max_age: timedelta | None = None) -> int: ...

    async def has_recent_empty_done(self, vip_id: UUID, *, since: datetime) -> bool: ...

    async def has_recent_failed(self, vip_id: UUID, *, since: datetime) -> bool: ...


class VipReader(Protocol):
    """VIP allowlist lookups needed by the queue (structural typing)."""

    async def get_by_telegram_user_id(
        self, telegram_user_id: int
    ) -> VipRecord | None: ...

    async def get_by_id(self, vip_id: UUID) -> VipRecord | None: ...

    async def list_active(self) -> list[VipRecord]: ...


class ProfilePresenceReader(Protocol):
    """Tells whether a VIP already has a profile row (structural typing)."""

    async def has_profile(self, vip_id: UUID) -> bool: ...


@dataclass(frozen=True, slots=True)
class EnqueueReport:
    """Outcome of one enqueue request (button / registration / missing-vips)."""

    status: str  # enqueued | already_pending | disabled | no_vip
    vip_id: UUID | None = None
    telegram_user_id: int = 0
    name: str | None = None
    steps: int = 0


@dataclass(frozen=True, slots=True)
class ProcessReport:
    """Outcome of one ``process_one`` unit (one transcript window)."""

    status: str  # processed | idle | disabled
    vip_id: UUID | None = None
    window_index: int | None = None
    outcome: str | None = None


class MemoryBackfillQueue:
    """Enqueue + one-window-per-cycle processing for VIP profile backfill."""

    def __init__(
        self,
        *,
        enabled: bool,
        store: BackfillQueueStore,
        backfill: MemoryBackfillService,
        vips: VipReader,
        history: HistoryReader,
        memories: ProfilePresenceReader,
        notifier: OwnerNotifierPort | None = None,
        window_size: int = 200,
        max_attempts: int = 3,
        wake: asyncio.Event | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._enabled = enabled
        self._store = store
        self._backfill = backfill
        self._vips = vips
        self._history = history
        self._memories = memories
        self._notifier = notifier
        self._window_size = max(1, int(window_size))
        self._max_attempts = max(1, int(max_attempts))
        self._wake = wake
        self._clock = clock or (lambda: datetime.now(UTC))
        # Fix round (S-F4): strong references to fire-and-forget tasks so GC
        # cannot collect them mid-flight (pattern TimerManager).
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # enqueue
    # ------------------------------------------------------------------

    async def enqueue_by_telegram_user(
        self, telegram_user_id: int
    ) -> EnqueueReport:
        """Enqueue the backfill job for one VIP (button / registration flow)."""
        if not self._enabled:
            logger.info(
                "backfill_enqueue_disabled",
                extra={"telegram_user_id": telegram_user_id},
            )
            return EnqueueReport(
                status="disabled", telegram_user_id=telegram_user_id
            )
        vip = await self._vips.get_by_telegram_user_id(telegram_user_id)
        if vip is None:
            logger.info(
                "backfill_enqueue_no_vip",
                extra={"telegram_user_id": telegram_user_id},
            )
            return EnqueueReport(
                status="no_vip", telegram_user_id=telegram_user_id
            )
        return await self._enqueue_vip(
            vip.id,
            chat_id=vip.telegram_user_id,
            name=vip.display_name,
            telegram_user_id=telegram_user_id,
        )

    async def _enqueue_vip(
        self,
        vip_id: UUID,
        *,
        chat_id: int,
        name: str | None,
        telegram_user_id: int,
        notify: bool = True,
    ) -> EnqueueReport:
        """Insert a pending job and notify the owner (best-effort).

        ``steps`` estimates how many windows (units) the job will take so the
        owner DM can promise a rough count ("~N pasos"). The wake event is set
        so a sleeping idle job starts processing immediately (R2).
        """
        # Fix round (L6/F7): count(*) instead of materializing the whole
        # history just to estimate the DM's "~N pasos".
        count = await self._history.count(chat_id)
        steps = max(1, math.ceil(count / self._window_size))
        record = await self._store.enqueue(vip_id, chat_id)
        label = name or str(telegram_user_id)
        if record is None:
            if notify:
                await self._notify(
                    f"El perfil de {label} ya está en cola (se procesará pronto)."
                )
            return EnqueueReport(
                status="already_pending",
                vip_id=vip_id,
                telegram_user_id=telegram_user_id,
                name=name,
                steps=steps,
            )
        if notify:
            await self._notify(
                f"Perfil de {label} en cola — se procesará en ~{steps} pasos"
            )
        if self._wake is not None:
            self._wake.set()
        logger.info(
            "backfill_enqueued",
            extra={
                "vip_id": str(vip_id),
                "telegram_user_id": telegram_user_id,
                "steps": steps,
            },
        )
        return EnqueueReport(
            status="enqueued",
            vip_id=vip_id,
            telegram_user_id=telegram_user_id,
            name=name,
            steps=steps,
        )

    def schedule_enqueue(self, telegram_user_id: int) -> None:
        """Fire-and-forget enqueue (pattern ``schedule_seed_for_new_vip``).

        Never blocks the caller (ficha button / registration confirm): the
        task runs the enqueue + owner DM in the background.
        """
        if not self._enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "backfill_enqueue_no_loop",
                extra={"telegram_user_id": telegram_user_id},
            )
            return
        task = loop.create_task(
            self._enqueue_safe(telegram_user_id),
            name=f"backfill-enqueue-{telegram_user_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _enqueue_safe(self, telegram_user_id: int) -> None:
        try:
            await self.enqueue_by_telegram_user(telegram_user_id)
        except Exception:
            logger.exception(
                "backfill_enqueue_failed",
                extra={"telegram_user_id": telegram_user_id},
            )

    async def enqueue_missing_vips(self) -> int:
        """Queue every active VIP with history and no profile (startup/on-demand).

        Guards: VIPs without any message history are skipped (the Telethon
        seed may still be pending) and VIPs marked ``done(empty_history)`` in
        the last 24h — or whose last job FAILED in the last 24h (fix round
        S2) — are not re-queued (R4 — no re-enqueue loop, no LLM burn per
        restart while the provider is degraded). Runs at startup / on demand,
        NEVER during the turn pipeline.
        """
        if not self._enabled:
            return 0
        since = self._clock() - timedelta(hours=24)
        enqueued = 0
        active = await self._vips.list_active()
        for vip in active:
            has_history = (await self._history.count(vip.telegram_user_id)) > 0
            if not has_history:
                continue
            if await self._memories.has_profile(vip.id):
                continue
            if await self._store.has_recent_empty_done(vip.id, since=since):
                continue
            # Fix round (S2): same 24h cooldown for FAILED jobs. The manual
            # ficha button bypasses this (enqueue ignores failed rows); only
            # the automatic path respects the cooldown.
            if await self._store.has_recent_failed(vip.id, since=since):
                continue
            report = await self._enqueue_vip(
                vip.id,
                chat_id=vip.telegram_user_id,
                name=vip.display_name,
                telegram_user_id=vip.telegram_user_id,
                notify=False,
            )
            if report.status == "enqueued":
                enqueued += 1
        logger.info("backfill_missing_enqueued", extra={"count": enqueued})
        return enqueued

    async def recover_stale(self, *, max_age: timedelta | None = None) -> int:
        """Requeue ``processing`` jobs untouched for more than ``max_age``.

        Delegates to the store; called once by ``BackfillJob.start()`` (jobs
        delegate to services — AGENTS.md §2.1). The age limit (fix round
        S-F3) keeps an overlapping restart from reclaiming a window the
        previous process is still extracting.
        """
        if not self._enabled:
            return 0
        return await self._store.recover_stale(max_age=max_age)

    # ------------------------------------------------------------------
    # processing (one unit = one window; lock = atomic pop + job loop)
    # ------------------------------------------------------------------

    async def process_one(self) -> ProcessReport:
        """Process exactly ONE transcript window of one VIP (job unit).

        ``pop_pending`` is the atomic claim (FOR UPDATE SKIP LOCKED): the
        job's ``asyncio.Lock``-style serialization is guaranteed by the single
        worker loop plus the DB claim (future multi-worker safe).
        """
        if not self._enabled:
            return ProcessReport(status="disabled")
        job = await self._store.pop_pending()
        if job is None:
            return ProcessReport(status="idle")

        try:
            # Fix round (L4/F6): deserializing the accumulated state INSIDE
            # the try — a corrupt/incompatible jsonb state is a unit failure
            # (retry → failed), never a job stuck in ``processing`` until the
            # next restart.
            already = [
                HechoExtracted.model_validate(f)
                for f in job.state.get("hechos", [])
                if isinstance(f, dict)
            ]
            res = await self._backfill.extract_window(
                job.vip_id,
                job.chat_id,
                window_index=job.window_index,
                already=already,
            )
        except ValidationError:
            logger.exception(
                "backfill_state_invalid",
                extra={"vip_id": str(job.vip_id), "job_id": str(job.id)},
            )
            return await self._handle_unit_failure(job, "state_invalid")
        except Exception:
            logger.exception(
                "backfill_window_unexpected_error",
                extra={"vip_id": str(job.vip_id), "job_id": str(job.id)},
            )
            return await self._handle_unit_failure(job, "window_unexpected_error")

        if res.failed:
            # Fix round (L8): the service labels the real cause (LLM failure
            # vs broken chat↔vip binding) so retries/last_error tell the
            # truth; the fallback keeps legacy fakes working.
            return await self._handle_unit_failure(
                job, res.failed_reason or "window_llm_failed"
            )

        if res.total_windows == 0:
            # Empty history OR empty transcript → done, no write (A6/R4). The
            # 24h guard in enqueue_missing_vips prevents a re-enqueue loop.
            await self._store.mark_done(job.id, outcome="empty_history")
            logger.info(
                "backfill_job_empty_history",
                extra={"vip_id": str(job.vip_id), "job_id": str(job.id)},
            )
            return ProcessReport(
                status="processed", vip_id=job.vip_id, outcome="empty_history"
            )

        hechos = already + res.hechos
        if job.window_index + 1 < res.total_windows:
            # More windows remain → persist progress and re-enqueue the SAME
            # VIP; the scheduler sleeps backfill_interval_sec between units
            # (also between windows of the same VIP — REQ-MEM-05).
            state = {"hechos": [h.model_dump() for h in hechos]}
            # Fix round (L5): the retry budget is PER WINDOW — a successful
            # window resets ``attempts`` so an early transient failure cannot
            # exhaust the retries of every later window of the same run.
            await self._store.save_progress(
                job.id,
                window_index=job.window_index + 1,
                state=state,
                attempts=0,
            )
            return ProcessReport(
                status="processed",
                vip_id=job.vip_id,
                window_index=job.window_index,
                outcome="window_done",
            )

        # Last window → consolidate + dedup + write profile in one shot.
        try:
            report = await self._backfill.finalize_profile(
                job.vip_id, job.chat_id, hechos=hechos, windows=res.total_windows
            )
        except Exception:
            logger.exception(
                "backfill_finalize_error",
                extra={"vip_id": str(job.vip_id), "job_id": str(job.id)},
            )
            return await self._handle_unit_failure(job, "finalize_error")

        if report.status == "failed":
            # Fix round (M1): a failed finalize WITHOUT an exception (e.g.
            # broken chat↔vip binding) is a UNIT failure — retry with backoff
            # and mark the job ``failed`` at max_attempts; never a terminal
            # ``done(outcome='failed')`` that buries the job with no retry,
            # no last_error and no visible failed state.
            return await self._handle_unit_failure(job, "finalize_failed")
        if report.status == "disabled":
            # Flag turned off mid-run: not a failure — explicit terminal
            # outcome keeps the status/outcome vocabulary coherent.
            await self._store.mark_done(job.id, outcome="disabled")
            logger.info(
                "backfill_job_disabled",
                extra={"vip_id": str(job.vip_id), "job_id": str(job.id)},
            )
            return ProcessReport(
                status="processed",
                vip_id=job.vip_id,
                window_index=job.window_index,
                outcome="disabled",
            )

        await self._store.mark_done(job.id, outcome=report.status)
        logger.info(
            "backfill_job_done",
            extra={
                "vip_id": str(job.vip_id),
                "job_id": str(job.id),
                "outcome": report.status,
                "facts": report.facts,
            },
        )
        return ProcessReport(
            status="processed",
            vip_id=job.vip_id,
            window_index=job.window_index,
            outcome=report.status,
        )

    async def _handle_unit_failure(
        self, job: BackfillJobRecord, error: str
    ) -> ProcessReport:
        """Retry a failed unit up to ``max_attempts``, then mark the job failed.

        The retry re-enqueues to ``pending`` so the scheduler spaces it with
        the same ``backfill_interval_sec`` (account protection).
        """
        attempts = job.attempts + 1
        if attempts >= self._max_attempts:
            await self._store.mark_failed(job.id, error=error)
            logger.error(
                "backfill_job_failed",
                extra={
                    "vip_id": str(job.vip_id),
                    "job_id": str(job.id),
                    "error": error,
                    "attempts": attempts,
                },
            )
            outcome = "failed"
        else:
            await self._store.requeue(job.id, attempts=attempts, error=error)
            logger.warning(
                "backfill_window_retry",
                extra={
                    "vip_id": str(job.vip_id),
                    "job_id": str(job.id),
                    "error": error,
                    "attempts": attempts,
                },
            )
            outcome = "failed_retry"
        return ProcessReport(
            status="processed",
            vip_id=job.vip_id,
            window_index=job.window_index,
            outcome=outcome,
        )

    async def _notify(self, text: str) -> None:
        """Best-effort owner DM (pattern vip_history_seed._notify_owner)."""
        if self._notifier is None:
            return
        try:
            await self._notifier.notify_info(text)
        except Exception:
            logger.exception("backfill_notify_failed", extra={"text": text})
