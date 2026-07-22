"""Turn lifecycle owner: one non-terminal turn per chat_id + supersede cascade."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from diana.application.ports import (
    BehaviorCanceller,
    PendingApprovalStore,
    TurnRecord,
    TurnStore,
)
from diana.cognitive.models import TurnStatus

logger = logging.getLogger("diana.application")


class ChatLockProvider:
    """Per-chat asyncio locks for in-process concurrency control."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def lock_for(self, chat_id: int) -> asyncio.Lock:
        async with self._guard:
            if chat_id not in self._locks:
                self._locks[chat_id] = asyncio.Lock()
            return self._locks[chat_id]


class TurnCoordinator:
    """Owns durable turn status transitions including Director sink."""

    def __init__(
        self,
        turns: TurnStore,
        approvals: PendingApprovalStore,
        behavior: BehaviorCanceller,
        *,
        locks: ChatLockProvider | None = None,
    ) -> None:
        self._turns = turns
        self._approvals = approvals
        self._behavior = behavior
        self._locks = locks or ChatLockProvider()

    async def begin_turn(
        self,
        *,
        chat_id: int,
        trigger_message_id: int | None = None,
        vip_id: UUID | None = None,
        turn_id: UUID | None = None,
    ) -> TurnRecord:
        """Create a new received turn after superseding any live turn for chat_id."""
        lock = await self._locks.lock_for(chat_id)
        async with lock:
            new_id = turn_id or uuid4()
            prior = await self._turns.list_non_terminal(chat_id)
            for old in prior:
                await self._turns.transition(
                    old.id,
                    TurnStatus.SUPERSEDED.value,
                    superseded_by=new_id,
                )
                logger.info(
                    "turn_superseded",
                    extra={
                        "turn_id": str(old.id),
                        "chat_id": chat_id,
                        "superseded_by": str(new_id),
                    },
                )
            if prior:
                await self._behavior.cancel_pending(chat_id, "new_message")
                cancelled = await self._approvals.cancel_waiting_for_chat(chat_id)
                logger.info(
                    "supersede_cascade",
                    extra={
                        "chat_id": chat_id,
                        "approvals_cancelled": cancelled,
                        "prior_count": len(prior),
                    },
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
                "turn_begun",
                extra={"turn_id": str(created.id), "chat_id": chat_id},
            )
            return created

    async def transition(
        self,
        turn_id: UUID,
        status: str | TurnStatus,
        **meta: object,
    ) -> TurnRecord:
        value = status.value if isinstance(status, TurnStatus) else str(status)
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

    async def transition_sink(
        self, turn_id: UUID, status: str | TurnStatus
    ) -> None:
        """TurnStatusSink adapter for CognitiveDirector injection."""
        await self.transition(turn_id, status)
