"""I/O ports for the application shell (no aiogram types)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TurnRecord(BaseModel):
    """Durable turn row shape used by application stores."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    chat_id: int
    status: str
    vip_id: UUID | None = None
    trigger_message_id: int | None = None
    superseded_by: UUID | None = None
    error: str | None = None


class ApprovalRecord(BaseModel):
    """pending_approvals row shape."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    turn_id: UUID
    chat_id: int
    business_connection_id: str
    draft_text: str
    status: str = "waiting"
    vip_id: UUID | None = None
    cognitive_summary: str | None = None
    evaluation: dict[str, Any] | None = None
    owner_message_id: int | None = None


class DeliveryRecord(BaseModel):
    """pending_deliveries row shape."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    chat_id: int
    business_connection_id: str
    texts: list[str]
    decision: dict[str, Any]
    scheduled_at: datetime
    status: str = "pending"
    turn_id: UUID
    vip_id: UUID | None = None


class DraftNotification(BaseModel):
    """Owner DM payload for draft approval (plain data, no aiogram)."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    chat_id: int
    vip_text: str
    draft_text: str
    reason: str
    evaluation_summary: str | None = None
    evaluation: dict[str, Any] | None = None
    business_connection_id: str
    reply_markup_spec: dict[str, Any] = Field(default_factory=dict)


class EscalationNotification(BaseModel):
    """Owner DM payload for escalation."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    chat_id: int
    reason: str
    vip_text: str | None = None
    tipo: str = "semantica"
    business_connection_id: str | None = None


class VipInboundMessage(BaseModel):
    """Application DTO for an inbound VIP business message."""

    model_config = ConfigDict(extra="forbid")

    chat_id: int
    text: str
    telegram_message_id: int | None = None
    business_connection_id: str | None = None
    vip_id: UUID | None = None


@runtime_checkable
class OwnerNotifierPort(Protocol):
    """Notify the owner via DM. Never accepts aiogram types."""

    async def notify_draft(self, payload: DraftNotification) -> int | None: ...

    async def notify_escalation(self, payload: EscalationNotification) -> None: ...

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None: ...


@runtime_checkable
class TurnStore(Protocol):
    async def create(self, turn: TurnRecord) -> TurnRecord: ...

    async def get(self, turn_id: UUID) -> TurnRecord | None: ...

    async def list_non_terminal(self, chat_id: int) -> list[TurnRecord]: ...

    async def transition(
        self,
        turn_id: UUID,
        status: str,
        *,
        superseded_by: UUID | None = None,
        error: str | None = None,
    ) -> TurnRecord: ...


@runtime_checkable
class PendingApprovalStore(Protocol):
    async def create_waiting(self, record: ApprovalRecord) -> ApprovalRecord: ...

    async def get_by_turn(self, turn_id: UUID) -> ApprovalRecord | None: ...

    async def mark_status(self, turn_id: UUID, status: str) -> None: ...

    async def cancel_waiting_for_chat(self, chat_id: int) -> int: ...

    async def list_waiting(self) -> list[ApprovalRecord]: ...


@runtime_checkable
class PendingDeliveryStore(Protocol):
    async def insert_pending(self, record: DeliveryRecord) -> DeliveryRecord: ...

    async def update_status(self, delivery_id: UUID, status: str, **meta: Any) -> None: ...

    async def cancel_for_chat(self, chat_id: int) -> int: ...

    async def list_pending(self) -> list[DeliveryRecord]: ...

    async def get(self, delivery_id: UUID) -> DeliveryRecord | None: ...


@runtime_checkable
class EscalationStore(Protocol):
    async def create(
        self, turn_id: UUID, *, tipo: str, motivo: str | None
    ) -> None: ...

    async def mark_notified(self, turn_id: UUID) -> None: ...


@runtime_checkable
class MessageHistoryWriter(Protocol):
    """Append-capable history writer (application side)."""

    async def append(
        self,
        chat_id: int,
        *,
        role: str,
        text: str,
        telegram_message_id: int | None = None,
        timestamp: datetime | None = None,
    ) -> None: ...

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]: ...


@runtime_checkable
class DeliveryResultWriter(Protocol):
    async def set_delivery_result(self, turn_id: UUID, result: dict) -> None: ...


@runtime_checkable
class TraceReader(Protocol):
    async def get_trace_keys(self, turn_id: UUID) -> set[str]: ...


@runtime_checkable
class BehaviorCanceller(Protocol):
    """Minimal cancel surface for TurnCoordinator (avoids circular imports)."""

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None: ...


__all__ = [
    "ApprovalRecord",
    "BehaviorCanceller",
    "DeliveryRecord",
    "DeliveryResultWriter",
    "DraftNotification",
    "EscalationNotification",
    "EscalationStore",
    "MessageHistoryWriter",
    "OwnerNotifierPort",
    "PendingApprovalStore",
    "PendingDeliveryStore",
    "TraceReader",
    "TurnRecord",
    "TurnStore",
    "VipInboundMessage",
]
