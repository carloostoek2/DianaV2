"""Turn lifecycle owner: concurrency guard for one non-terminal turn per chat.

Single question (Anexo G.1): given (chat_id, autor, event), create a new turn
or affect existing non-terminal turns? Never reasons on message text, never
calls an LLM, never produces draft text or cognitive Decision actions.

English runtime tokens ↔ Anexo G (Spanish):
  autor="vip" | "owner"          ↔ autor: "vip" | "dueña"
  action="create"                ↔ accion: "crear"
  action="replace"               ↔ accion: "reemplazar"
  action="discard_owner_message" ↔ accion: "descartar_mensaje_dueña"
  CoordinateResult               ↔ CoordinatorOutput
  coordinate / coordinate_unlocked ↔ G.2 entry under G.4 lock
  ChatLockTimeoutError           ↔ G.5 lock failure (F1: raise, no enqueue)

F1 residuals (out of scope here):
  - Multi-process G.4: Postgres SELECT … FOR UPDATE / advisory lock across workers
  - G.5 durable message requeue/outbox after lock timeout exhausts retries
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID, uuid4

from diana.application.observability import log_swallowed
from diana.application.ports import (
    BehaviorCanceller,
    PendingApprovalStore,
    TurnRecord,
    TurnStore,
)
from diana.cognitive.exceptions import TurnSupersededError
from diana.cognitive.models import TERMINAL_TURN_STATUSES, TurnStatus, parse_turn_status

logger = logging.getLogger("diana.application")

Autor = Literal["vip", "owner"]
CoordinateAction = Literal["create", "replace", "discard_owner_message"]

LOCK_ACQUIRE_TIMEOUT_S = 5.0
LOCK_ACQUIRE_RETRIES = 2
_LOCK_BACKOFF_BASE_S = 0.05


class RecontactLifecycle(Protocol):
    """Cancel + re-seed recontact schedule on VIP activity (BR-07 / R3)."""

    async def cancel_recontact(self, vip_id: UUID) -> bool: ...

    async def schedule_recontact(self, vip_id: UUID) -> object | None: ...


# Backward-compatible alias (cancel-only callers still type-check loosely).
RecontactCanceller = RecontactLifecycle


class ChatLockTimeoutError(TimeoutError):
    """Raised when per-chat lock cannot be acquired (G.5 F1 loud fail)."""


@dataclass(frozen=True, slots=True)
class CoordinateResult:
    """G.2 output: English action + optional turn id for create/replace."""

    action: CoordinateAction
    turn_id: UUID | None


class ChatLockProvider:
    """Per-chat asyncio locks — process-local, single-instance only.

    Multi-process G.4 (Postgres advisory / SELECT FOR UPDATE) remains residual;
    see docs/OPS_SINGLE_INSTANCE.md.
    """

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def lock_for(self, chat_id: int) -> asyncio.Lock:
        async with self._guard:
            if chat_id not in self._locks:
                self._locks[chat_id] = asyncio.Lock()
            return self._locks[chat_id]


class TurnCoordinator:
    """Owns turn entry (G.3) and durable status transitions including Director sink."""

    def __init__(
        self,
        turns: TurnStore,
        approvals: PendingApprovalStore,
        behavior: BehaviorCanceller,
        *,
        locks: ChatLockProvider | None = None,
        lock_acquire_timeout_s: float = LOCK_ACQUIRE_TIMEOUT_S,
        lock_acquire_retries: int = LOCK_ACQUIRE_RETRIES,
        recontact: RecontactLifecycle | None = None,
        feature_recontact_enabled: bool = False,
    ) -> None:
        self._turns = turns
        self._approvals = approvals
        self._behavior = behavior
        self._locks = locks or ChatLockProvider()
        self._lock_acquire_timeout_s = lock_acquire_timeout_s
        self._lock_acquire_retries = lock_acquire_retries
        self._recontact = recontact
        self._feature_recontact_enabled = feature_recontact_enabled
        self._owner_interventions: dict[int, float] = {}
        self._turn_chat_ids: dict[UUID, int] = {}
        # Per-chat VIP inbound epoch: newer message aborts older in-flight work.
        self._vip_epochs: dict[int, int] = {}
        self._turn_vip_epochs: dict[UUID, int] = {}

    @asynccontextmanager
    async def chat_scope(self, chat_id: int) -> AsyncIterator[None]:
        """Hold the per-chat lock; G.5 F1 timeout + bounded retry then raise."""
        lock = await self._locks.lock_for(chat_id)
        attempts = self._lock_acquire_retries + 1
        acquired = False
        last_exc: BaseException | None = None
        for attempt in range(attempts):
            try:
                await asyncio.wait_for(
                    lock.acquire(),
                    timeout=self._lock_acquire_timeout_s,
                )
                acquired = True
                break
            except TimeoutError as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(_LOCK_BACKOFF_BASE_S * (attempt + 1))
        if not acquired:
            logger.error(
                "chat_lock_timeout",
                extra={
                    "chat_id": chat_id,
                    "timeout_s": self._lock_acquire_timeout_s,
                    "retries": self._lock_acquire_retries,
                },
            )
            raise ChatLockTimeoutError(
                f"chat lock acquire timed out for chat_id={chat_id}"
            ) from last_exc
        try:
            yield
        finally:
            lock.release()

    def mark_owner_intervened(self, chat_id: int) -> None:
        """Record that the owner wrote in a VIP chat (no lock needed).

        Called by OwnerDetectionMiddleware before attempting coordinate()
        so the flag is set even when the chat lock is held by the pipeline.
        """
        self._owner_interventions[chat_id] = _time.monotonic()

    def is_owner_intervened(
        self, chat_id: int, since: float | None = None
    ) -> bool:
        """Check whether the owner wrote in *chat_id* during the current turn."""
        ts = self._owner_interventions.get(chat_id)
        if ts is None:
            return False
        if since is not None and ts < since:
            return False
        return True

    def clear_owner_intervention(self, chat_id: int) -> None:
        self._owner_interventions.pop(chat_id, None)

    def bump_vip_epoch(self, chat_id: int) -> int:
        """Advance VIP inbound generation for *chat_id*; return new epoch token."""
        n = self._vip_epochs.get(chat_id, 0) + 1
        self._vip_epochs[chat_id] = n
        return n

    def current_vip_epoch(self, chat_id: int) -> int:
        return self._vip_epochs.get(chat_id, 0)

    def bind_turn_vip_epoch(self, turn_id: UUID, chat_id: int, epoch: int) -> None:
        """Associate a live turn with the VIP epoch that minted it."""
        self._turn_chat_ids[turn_id] = chat_id
        self._turn_vip_epochs[turn_id] = epoch

    def is_vip_epoch_current(self, chat_id: int, epoch: int) -> bool:
        return self._vip_epochs.get(chat_id, 0) == epoch

    async def coordinate(
        self,
        chat_id: int,
        autor: Autor,
        *,
        trigger_message_id: int | None = None,
        vip_id: UUID | None = None,
        turn_id: UUID | None = None,
    ) -> CoordinateResult:
        """G.2 entry: decide create | replace | discard_owner_message under lock."""
        async with self.chat_scope(chat_id):
            return await self.coordinate_unlocked(
                chat_id,
                autor,
                trigger_message_id=trigger_message_id,
                vip_id=vip_id,
                turn_id=turn_id,
            )

    async def coordinate_unlocked(
        self,
        chat_id: int,
        autor: Autor,
        *,
        trigger_message_id: int | None = None,
        vip_id: UUID | None = None,
        turn_id: UUID | None = None,
    ) -> CoordinateResult:
        """G.3 matrix; caller MUST already hold ``chat_scope(chat_id)``."""
        if autor not in ("vip", "owner"):
            raise ValueError(f"invalid autor: {autor!r}")

        if autor == "owner":
            prior = await self._supersede_nonterminal(
                chat_id,
                superseded_by=None,
                cancel_reason="owner_message",
            )
            self.clear_owner_intervention(chat_id)
            result = CoordinateResult(action="discard_owner_message", turn_id=None)
            logger.info(
                "coordinate_result",
                extra={
                    "chat_id": chat_id,
                    "autor": autor,
                    "action": result.action,
                    "prior_count": len(prior),
                    "trigger_message_id": trigger_message_id,
                },
            )
            return result

        # VIP path: BR-07 cancel pending recontact, then re-seed inactivity window.
        if (
            self._feature_recontact_enabled
            and self._recontact is not None
            and vip_id is not None
        ):
            try:
                cancelled = await self._recontact.cancel_recontact(vip_id)
                if cancelled:
                    logger.info(
                        "recontact_cancelled_on_vip_message",
                        extra={"vip_id": str(vip_id), "chat_id": chat_id},
                    )
            except Exception:
                log_swallowed(
                    logger,
                    "recontact_cancel_on_vip_message_failed",
                    vip_id=str(vip_id),
                    chat_id=chat_id,
                )
            try:
                scheduled = await self._recontact.schedule_recontact(vip_id)
                if scheduled is not None:
                    logger.info(
                        "recontact_scheduled_on_vip_message",
                        extra={"vip_id": str(vip_id), "chat_id": chat_id},
                    )
            except Exception:
                log_swallowed(
                    logger,
                    "recontact_schedule_on_vip_message_failed",
                    vip_id=str(vip_id),
                    chat_id=chat_id,
                )

        # VIP path: create or replace.
        new_id = turn_id or uuid4()
        prior = await self._turns.list_non_terminal(chat_id)
        action: CoordinateAction = "replace" if prior else "create"
        if prior:
            await self._supersede_nonterminal(
                chat_id,
                superseded_by=new_id,
                cancel_reason="new_message",
            )

        record = TurnRecord(
            id=new_id,
            chat_id=chat_id,
            status=TurnStatus.RECEIVED.value,
            vip_id=vip_id,
            trigger_message_id=trigger_message_id,
        )
        created = await self._turns.create(record)
        logger.info(
            "coordinate_result",
            extra={
                "chat_id": chat_id,
                "autor": autor,
                "action": action,
                "turn_id": str(created.id),
                "prior_count": len(prior),
            },
        )
        logger.info(
            "turn_begun",
            extra={"turn_id": str(created.id), "chat_id": chat_id},
        )
        return CoordinateResult(action=action, turn_id=created.id)

    async def reset_chat_session(
        self, chat_id: int, *, reason: str = "sandbox_reset"
    ) -> int:
        """Supersede non-terminal turns for chat; cancel delivery/approvals.

        Does not deactivate sandbox sessions (application concern).
        Returns the count of superseded turns.
        """
        async with self.chat_scope(chat_id):
            prior = await self._supersede_nonterminal(
                chat_id, superseded_by=None, cancel_reason=reason
            )
            return len(prior)

    async def _supersede_nonterminal(
        self,
        chat_id: int,
        *,
        superseded_by: UUID | None,
        cancel_reason: str,
    ) -> list[TurnRecord]:
        """Mark all live turns superseded and cascade cancel delivery/approvals."""
        prior = await self._turns.list_non_terminal(chat_id)
        for old in prior:
            await self._turns.transition(
                old.id,
                TurnStatus.SUPERSEDED.value,
                superseded_by=superseded_by,
            )
            logger.info(
                "turn_superseded",
                extra={
                    "turn_id": str(old.id),
                    "chat_id": chat_id,
                    "superseded_by": str(superseded_by) if superseded_by else None,
                    "reason": cancel_reason,
                },
            )
        if prior:
            await self._behavior.cancel_pending(chat_id, cancel_reason)
            cancelled = await self._approvals.cancel_waiting_for_chat(chat_id)
            logger.info(
                "supersede_cascade",
                extra={
                    "chat_id": chat_id,
                    "approvals_cancelled": cancelled,
                    "prior_count": len(prior),
                    "reason": cancel_reason,
                },
            )
        return prior

    async def begin_turn(
        self,
        *,
        chat_id: int,
        trigger_message_id: int | None = None,
        vip_id: UUID | None = None,
        turn_id: UUID | None = None,
    ) -> TurnRecord:
        """VIP wrapper: coordinate create/replace and return the new TurnRecord."""
        result = await self.coordinate(
            chat_id,
            "vip",
            trigger_message_id=trigger_message_id,
            vip_id=vip_id,
            turn_id=turn_id,
        )
        assert result.turn_id is not None
        record = await self._turns.get(result.turn_id)
        assert record is not None
        self._turn_chat_ids[record.id] = chat_id
        self.clear_owner_intervention(chat_id)
        return record

    async def get_turn(self, turn_id: UUID) -> TurnRecord | None:
        """Load a durable turn row."""
        return await self._turns.get(turn_id)

    async def begin_turn_unlocked(
        self,
        *,
        chat_id: int,
        trigger_message_id: int | None = None,
        vip_id: UUID | None = None,
        turn_id: UUID | None = None,
    ) -> TurnRecord:
        """VIP wrapper body; caller must already hold ``chat_scope(chat_id)``."""
        result = await self.coordinate_unlocked(
            chat_id,
            "vip",
            trigger_message_id=trigger_message_id,
            vip_id=vip_id,
            turn_id=turn_id,
        )
        assert result.turn_id is not None
        record = await self._turns.get(result.turn_id)
        assert record is not None
        self._turn_chat_ids[record.id] = chat_id
        self.clear_owner_intervention(chat_id)
        return record

    async def transition(
        self,
        turn_id: UUID,
        status: str | TurnStatus,
        **meta: object,
    ) -> TurnRecord:
        """Director status sink + durable transitions.

        Before applying a non-terminal progress status, abort if the owner
        intervened or a newer VIP message advanced the chat epoch — total
        cancel (no approve/send from the stale turn).
        """
        value = status.value if isinstance(status, TurnStatus) else str(status)
        # Terminal writes (failed/superseded/…) skip stale checks so cleanup works.
        if value not in {s.value for s in TERMINAL_TURN_STATUSES}:
            await self._raise_if_turn_cancelled(turn_id)
        superseded_by = meta.get("superseded_by")
        error = meta.get("error")
        return await self._turns.transition(
            turn_id,
            value,
            superseded_by=superseded_by if isinstance(superseded_by, UUID) else None,
            error=error if isinstance(error, str) else None,
        )

    async def mark_failed(
        self, turn_id: UUID, error: str | None = None
    ) -> TurnRecord:
        return await self.transition(turn_id, TurnStatus.FAILED, error=error)

    async def _raise_if_turn_cancelled(self, turn_id: UUID) -> None:
        """Supersede + raise when owner or newer VIP invalidated this turn."""
        chat_id = self._turn_chat_ids.get(turn_id)
        if chat_id is None:
            return
        if self.is_owner_intervened(chat_id):
            await self._supersede_nonterminal(
                chat_id, superseded_by=None, cancel_reason="owner_message"
            )
            raise TurnSupersededError()
        bound = self._turn_vip_epochs.get(turn_id)
        if bound is not None and self._vip_epochs.get(chat_id, 0) != bound:
            await self._supersede_nonterminal(
                chat_id, superseded_by=None, cancel_reason="new_message"
            )
            raise TurnSupersededError()

    async def transition_sink(
        self, turn_id: UUID, status: str | TurnStatus
    ) -> None:
        """TurnStatusSink adapter — same cancel checks as ``transition``."""
        await self.transition(turn_id, status)

    def is_terminal_status(self, status: str) -> bool:
        try:
            return parse_turn_status(status) in TERMINAL_TURN_STATUSES
        except ValueError:
            return False


__all__ = [
    "Autor",
    "ChatLockProvider",
    "ChatLockTimeoutError",
    "CoordinateAction",
    "CoordinateResult",
    "LOCK_ACQUIRE_RETRIES",
    "LOCK_ACQUIRE_TIMEOUT_S",
    "RecontactCanceller",
    "RecontactLifecycle",
    "TurnCoordinator",
]
