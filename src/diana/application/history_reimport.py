"""HistoryReimportService — slow, scheduled re-import of pre-existing VIP history.

Product: VIPs registered before the history-seed fix never got their
pre-existing personal-chat history imported (the old seed skipped chats that
already had system rows), so their memory backfill ran on incomplete history.
This service re-runs the (now idempotent) seed for existing VIPs and re-enqueues
the memory backfill only when the import actually added messages.

Pacing (owner account protection): one VIP per ``process_next()`` call — the
scheduler sleeps ``history_reimport_interval_sec`` (default 3600) between units,
exactly like the backfill scheduler. Telegram never sees more than one
personal-session fetch per hour.

Rotation: a durable cursor (``ReimportCursorStore``) remembers the last
processed VIP so a restart resumes mid-cycle instead of repeating the first
VIP. After the last VIP the cycle wraps to the first, so VIPs added later are
picked up automatically. The seed is idempotent (``append_missing`` dedups by
telegram_message_id), so re-visits append nothing and never duplicate rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from diana.application.memory_backfill_queue import EnqueueReport
from diana.application.vip_history_seed import SeedOutcome

logger = logging.getLogger("diana.application")

__all__ = [
    "HistoryReimportService",
    "ReimportCursorStore",
    "ReimportReport",
]


class ReimportVipReader(Protocol):
    """Active VIP list for the rotation (structural typing; SqlVipStore)."""

    async def list_active(self) -> list[object]: ...


class ReimportSeed(Protocol):
    """Idempotent history import (structural typing; VipHistorySeedService)."""

    async def seed_for_new_vip(
        self,
        telegram_user_id: int,
        *,
        username: str | None = None,
    ) -> SeedOutcome: ...


class ReimportBackfillEnqueuer(Protocol):
    """Memory-backfill enqueue (structural typing; MemoryBackfillQueue)."""

    async def enqueue_by_telegram_user(
        self, telegram_user_id: int, *, notify: bool = True
    ) -> EnqueueReport: ...


class ReimportCursorStore(Protocol):
    """Durable rotation cursor (implemented over ``system_config``)."""

    async def get_cursor(self) -> int | None: ...

    async def set_cursor(self, telegram_user_id: int) -> None: ...


@dataclass(frozen=True, slots=True)
class ReimportReport:
    """Outcome of one re-import unit (one VIP), for logs + owner DM."""

    status: Literal["processed", "no_vip"]
    telegram_user_id: int = 0
    imported: int = 0
    index: int = 0  # 1-based position within the active VIP list
    total: int = 0
    backfill: str | None = None  # enqueued | already_pending | disabled | skipped
    error: str | None = None


class HistoryReimportService:
    """One-VIP-per-cycle re-import + backfill re-enqueue (scheduler drives)."""

    def __init__(
        self,
        *,
        vips: ReimportVipReader,
        seed: ReimportSeed,
        backfill: ReimportBackfillEnqueuer,
        cursor: ReimportCursorStore,
        notifier: object | None = None,
    ) -> None:
        self._vips = vips
        self._seed = seed
        self._backfill = backfill
        self._cursor = cursor
        self._notifier = notifier

    async def process_next(self) -> ReimportReport:
        """Re-import the next active VIP after the cursor (wrap-around).

        One VIP per call; the scheduler paces calls. Idempotent: a VIP whose
        history is already fully imported appends nothing (imported=0) and does
        not re-enqueue the backfill.
        """
        active = list(await self._vips.list_active())
        if not active:
            return ReimportReport(status="no_vip")
        cursor = await self._cursor.get_cursor()
        nxt = next(
            (v for v in active if int(v.telegram_user_id) > (cursor or -1)),
            active[0],
        )
        uid = int(nxt.telegram_user_id)
        index = next(
            i
            for i, v in enumerate(active, start=1)
            if int(v.telegram_user_id) == uid
        )
        total = len(active)

        outcome: SeedOutcome | None = None
        error: str | None = None
        try:
            outcome = await self._seed.seed_for_new_vip(uid)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        imported = 0
        if error is None and outcome is not None and outcome.kind == "ok":
            imported = int(outcome.count or 0)

        backfill_status: str | None = None
        if imported > 0:
            # notify=False: this service reports its own single DM per VIP.
            report = await self._backfill.enqueue_by_telegram_user(
                uid, notify=False
            )
            backfill_status = str(report.status)

        # Advance the cursor regardless (idempotent: a failure is retried on the
        # next rotation, still at most one VIP per hour).
        await self._cursor.set_cursor(uid)
        logger.info(
            "history_reimport_unit",
            extra={
                "telegram_user_id": uid,
                "index": index,
                "total": total,
                "imported": imported,
                "backfill": backfill_status,
                "error": error,
            },
        )
        await self._notify(uid, index, total, imported, backfill_status, error)
        return ReimportReport(
            status="processed",
            telegram_user_id=uid,
            imported=imported,
            index=index,
            total=total,
            backfill=backfill_status,
            error=error,
        )

    async def _notify(
        self,
        uid: int,
        index: int,
        total: int,
        imported: int,
        backfill: str | None,
        error: str | None,
    ) -> None:
        """Owner DM only for meaningful events (imported > 0 or failure).

        A no-op cycle (nothing new to import) stays silent — with 1 unit/hour
        this is the common case and a DM per hour would be noise.
        """
        if self._notifier is None:
            return
        step = f" (paso {index}/{total})"
        if error is not None:
            text = (
                f"Re-importado de historial del VIP {uid}{step} falló; "
                "se reintentará en la próxima pasada."
            )
        elif imported > 0:
            if backfill == "already_pending":
                tail = "el perfil ya estaba en cola para reprocesar."
            elif backfill == "disabled":
                tail = "el reproceso de perfil no está disponible."
            else:
                tail = "el perfil quedó en cola para reprocesar."
            nuevo = "nuevo" if imported == 1 else "nuevos"
            importado = "importado" if imported == 1 else "importados"
            text = (
                f"Re-importado de historial del VIP {uid}{step}: "
                f"{imported} mensaje{'s' if imported != 1 else ''} "
                f"{nuevo} {importado}; {tail}"
            )
        else:
            return
        try:
            await self._notifier.notify_info(text)
        except Exception:
            logger.exception(
                "history_reimport_notify_failed",
                extra={"telegram_user_id": uid},
            )
