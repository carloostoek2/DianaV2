"""ProfileSynthesisTriggerService — cheap, LLM-free triggers for Fase 1 resynthesis.

Application service (AGENTS.md §2.1): decides WHEN a VIP profile should be
resynthesized, without any LLM call. Four OR conditions, evaluated in priority
order (the first match wins as the trigger label, one enqueue per VIP):

- (d) ``signal.should_trigger_synthesis`` (emotional detector, immediate —
  spec transversal §Puntos de integración 1).
- (c) strong signal (``strong_signal_heuristics.match`` on the message text).
- (a) volume: ``vip``-channel turns since ``last_synthesized_at`` >= threshold.
- (b) inactivity (``session_close``) is NOT evaluated per-turn — only the
  periodic ``scan_inactivity`` (the per-turn path cannot know the chat closed).

Concurrency = in-memory guard (``_pending`` dict + ``_in_flight`` set): one
pending/processing synthesis per VIP within the process, so the per-turn hook
and the scan never double-fire. The guard is NOT a durable queue (Fase 5
upgrade; a restart simply re-scans — ``last_synthesized_at`` persists, A3).

Thresholds are fixed constants with a MANUAL override via ``apply_overrides``
(hydrated from ``system_config`` key ``profile_synthesis`` at boot). NEVER
auto-calibrated (incident lesson).

Purity: imports only stdlib + ``application.ports`` + ``cognitive.models``
(precedente ``autonomous_mode_service``); no aiogram, no infrastructure.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from diana.application.ports import (
    ProfileSynthesisQueueStore,
    VipProfileRecord,
)
from diana.application.strong_signal_heuristics import match as strong_signal_match
from diana.cognitive.models import SynthesisTrigger

logger = logging.getLogger("diana.application")

__all__ = [
    "ProfileSynthesisTriggerService",
    "SynthesisActivitySource",
    "SynthesisProfileReader",
]


class SynthesisProfileReader(Protocol):
    """Profile reader for the trigger (structural typing, pattern BackfillQueueStore)."""

    async def get_or_create(self, vip_id: UUID) -> VipProfileRecord: ...


class SynthesisActivitySource(Protocol):
    """Activity counters for the trigger (structural typing)."""

    async def count_messages_since(
        self, vip_id: UUID, *, since: datetime | None
    ) -> int: ...

    async def list_vips_with_activity_older_than(
        self, older_than: datetime, *, limit: int
    ) -> list[tuple[UUID, datetime]]: ...


class ProfileSynthesisTriggerService:
    """Evaluates the Fase 1 resynthesis conditions and enqueues pending VIPs.

    ``_pending`` is a ``dict[UUID, SynthesisTrigger]`` so the first condition
    that matched owns the label (later conditions for the same VIP are
    deduped); ``_in_flight`` blocks re-enqueue while the job synthesizes.
    """

    def __init__(
        self,
        *,
        profile_reader: SynthesisProfileReader,
        activity: SynthesisActivitySource,
        volume_threshold: int,
        inactivity_minutes: int,
        # Fila 4 C4: optional durable queue (migration 031). When wired, the
        # per-turn hook and the scan PERSIST enqueues; the job drains from the
        # queue and releases on completion — pending work survives restarts.
        queue: ProfileSynthesisQueueStore | None = None,
    ) -> None:
        self._profile_reader = profile_reader
        self._activity = activity
        self._volume_threshold = max(1, int(volume_threshold))
        self._inactivity_minutes = max(1, int(inactivity_minutes))
        self._pending: dict[UUID, SynthesisTrigger] = {}
        self._in_flight: set[UUID] = set()
        self._queue = queue

    def has_durable_queue(self) -> bool:
        return self._queue is not None

    def apply_overrides(self, config: dict) -> None:
        """Manual threshold override from ``system_config`` key ``profile_synthesis``.

        This is the ONLY override point — never auto-calibrated. Missing keys
        are ignored; invalid values are rejected without crashing.
        ``volume_threshold`` and ``inactivity_minutes`` are clamped to a
        minimum of 1 (config-typo safety).
        """
        if not isinstance(config, dict):
            return
        try:
            raw = config.get("volume_threshold")
            if raw is not None:
                self._volume_threshold = max(1, int(raw))
        except (TypeError, ValueError):
            pass
        try:
            raw = config.get("inactivity_minutes")
            if raw is not None:
                self._inactivity_minutes = max(1, int(raw))
        except (TypeError, ValueError):
            pass

    def enqueue(self, vip_id: UUID, trigger: SynthesisTrigger) -> bool:
        """Mark ``vip_id`` for synthesis if not already pending/in-flight.

        Returns False when the VIP is already pending or being synthesized
        (dedup — one synthesis per VIP even when several conditions match or
        the scan coincides with the per-turn hook).
        """
        if vip_id in self._pending or vip_id in self._in_flight:
            return False
        self._pending[vip_id] = trigger
        return True

    async def enqueue_durable(self, vip_id: UUID, trigger: SynthesisTrigger) -> bool:
        """In-memory dedup + durable pending upsert (Fila 4 C4).

        Returns False when the VIP is already pending/in-flight in THIS
        process (fast dedup — no DB write). Otherwise persists the pending row
        (a re-enqueue from another process refreshes the trigger).
        """
        if vip_id in self._pending or vip_id in self._in_flight:
            return False
        if self._queue is not None:
            try:
                await self._queue.upsert_pending(vip_id, trigger)
            except Exception:
                logger.exception(
                    "profile_synthesis_queue_enqueue_failed",
                    extra={"vip_id": str(vip_id), "trigger": trigger},
                )
                # Fail-open: keep the in-memory guard so the job still sees it.
        self._pending[vip_id] = trigger
        return True

    async def evaluate_and_maybe_enqueue(
        self,
        vip_id: UUID | None,
        *,
        text: str | None = None,
        signal: object | None = None,
    ) -> str | None:
        """Evaluate the OR conditions and enqueue on the first match.

        Priority: emotional signal (d) > strong signal (c) > volume (a). The
        emotional signal is immediate (no message count); strong signal and
        volume share the per-turn hook. Inactivity (b) lives in
        ``scan_inactivity`` only. Returns the trigger label that fired, or None
        if nothing fired (and nothing was enqueued).
        """
        if vip_id is None:
            return None
        # S1: already pending/in-flight → the enqueue would be a no-op, so skip
        # the DB reads entirely (in a burst of one pending VIP, each message no
        # longer pays 2 queries in the hot path for a discarded result).
        if vip_id in self._pending or vip_id in self._in_flight:
            return None
        trigger: SynthesisTrigger | None = None
        if signal is not None and getattr(signal, "should_trigger_synthesis", False):
            trigger = "emotional_signal"
        elif text and strong_signal_match(text):
            trigger = "strong_signal"
        else:
            current = await self._profile_reader.get_or_create(vip_id)
            count = await self._activity.count_messages_since(
                vip_id, since=current.last_synthesized_at
            )
            if count >= self._volume_threshold:
                trigger = "volume"
        # The guard is re-checked inside enqueue (an await may have raced with
        # the scan/drain); when it dedups, nothing was enqueued → return None,
        # coherent with the docstring contract (fix round nit).
        if trigger is not None and not await self._enqueue(vip_id, trigger):
            return None
        return trigger

    async def scan_inactivity(self, now: datetime) -> int:
        """Enqueue ``session_close`` for VIPs with new activity older than the cutoff.

        ``cutoff = now - inactivity_minutes``. A VIP is enqueued only when it
        HAS new activity since its last synthesis (``last_synthesized_at`` None
        → the whole history is new). The in-memory guard doubles as the spec
        1.1 "no pending resynthesis" marker. Returns how many were enqueued.
        """
        cutoff = now - timedelta(minutes=self._inactivity_minutes)
        candidates = await self._activity.list_vips_with_activity_older_than(
            cutoff, limit=100
        )
        enqueued = 0
        for vip_id, last_activity in candidates:
            profile = await self._profile_reader.get_or_create(vip_id)
            has_new = (
                profile.last_synthesized_at is None
                or last_activity > profile.last_synthesized_at
            )
            if has_new:
                if await self._enqueue(vip_id, "session_close"):
                    enqueued += 1
        return enqueued

    async def _enqueue(
        self, vip_id: UUID, trigger: SynthesisTrigger
    ) -> bool:
        """Route to the in-memory or durable enqueue (Fila 4 C4)."""
        if self._queue is not None:
            return await self.enqueue_durable(vip_id, trigger)
        return self.enqueue(vip_id, trigger)

    def drain_pending(self) -> list[tuple[UUID, SynthesisTrigger]]:
        """Move every pending VIP to in-flight and return ``[(vip_id, trigger)]``.

        The job synthesizes each item and must call ``release`` in a ``finally``
        so the VIP is re-enqueueable even when synthesis fails.
        """
        items = list(self._pending.items())
        self._pending.clear()
        for vip_id, _trigger in items:
            self._in_flight.add(vip_id)
        return items

    async def drain_pending_durable(self, limit: int = 100) -> list[tuple[UUID, SynthesisTrigger]]:
        """Claim pending rows from the durable queue (CAS) + in-memory guard.

        Returns ``[(vip_id, trigger)]`` for the job to synthesize; ``release``
        (durable) must be called in a ``finally`` per item.
        """
        if self._queue is None:
            return self.drain_pending()
        claimed = await self._queue.drain(limit=limit)
        items: list[tuple[UUID, SynthesisTrigger]] = []
        for record in claimed:
            if record.vip_id in self._pending:
                del self._pending[record.vip_id]
            self._in_flight.add(record.vip_id)
            items.append((record.vip_id, record.trigger))
        return items

    def release(self, vip_id: UUID) -> None:
        """Allow ``vip_id`` to be enqueued again after synthesis (finally)."""
        self._in_flight.discard(vip_id)

    async def release_durable(self, vip_id: UUID) -> None:
        """Durable release: remove the queue row + in-memory release (finally)."""
        if self._queue is not None:
            try:
                await self._queue.complete(vip_id)
            except Exception:
                logger.exception(
                    "profile_synthesis_queue_release_failed",
                    extra={"vip_id": str(vip_id)},
                )
        self._in_flight.discard(vip_id)

    async def recover_stale(self, max_age_seconds: int = 3600) -> int:
        """Reset abandoned ``processing`` rows back to ``pending`` (job start)."""
        if self._queue is None:
            return 0
        try:
            return await self._queue.recover_stale(max_age_seconds=max_age_seconds)
        except Exception:
            logger.exception("profile_synthesis_queue_recover_failed")
            return 0
