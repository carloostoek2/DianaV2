"""I/O ports for the application shell (no aiogram types)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
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
    """pending_approvals row shape.

    Status values used in F1:
    - waiting: owner has not acted
    - claimed: atomic claim before deliver (CAS winner)
    - approved / corrected: resolved after successful deliver
    - cancelled / expired: terminal non-deliver
    """

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
    trigger_message_id: int | None = None


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
    vip_display_name: str | None = None
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


class DoctrineNotification(BaseModel):
    """Notification to the owner with a gray zone doctrine query."""

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    chat_id: int
    vip_text: str
    draft_text: str | None = None
    evaluation_summary: str
    reason: str
    business_connection_id: str | None = None
    reply_markup_spec: dict | None = None


@runtime_checkable
class GrayZoneQueryView(Protocol):
    """Minimal query view used by AdminService.send_doctrine_query.

    Provides a stable interface over the ORM GrayZoneQuery row so the
    application layer does not depend on infrastructure model shapes.
    """

    id: UUID
    draft: str


@runtime_checkable
class GrayZoneServicePort(Protocol):
    """Application service for the gray zone query lifecycle.

    Exposes the methods consumed by telegram handlers so the telegram layer
    can depend on the protocol instead of ``Any``.
    """

    async def get_open_query_by_turn_id(self, turn_id: UUID) -> GrayZoneQueryView | None: ...

    async def resolve_with_doctrine(
        self,
        query_id: UUID,
        generalization: str,
        rule: str,
    ) -> object: ...

    async def confirm_and_apply(
        self, query_id: UUID, candidate_id: UUID
    ) -> object: ...

    async def discard_and_close(self, query_id: UUID) -> object: ...

    async def expire_old_queries(
        self, timeout_hours: int | None = None
    ) -> list[object]: ...


DeliveryMode = Literal["supervised", "autonomous", "fake_delivery"]


class DeliveryContext(BaseModel):
    """Context required to act a message toward a VIP chat."""

    model_config = ConfigDict(extra="forbid")

    chat_id: int
    business_connection_id: str
    vip_id: UUID | None = None
    mode: DeliveryMode = "supervised"
    telegram_message_id: int | None = None
    is_frozen: bool = False
    # When True the pre-send wait was already served before the pipeline,
    # so BehaviorEngine delivers without extra initial delay (typing still applies).
    skip_initial_delay: bool = False
    # Advanced behavior (H3.6) — fail-closed defaults; dual-gated in engine.
    allow_split: bool = False
    allow_human_quirks: bool = False
    split_chars: int = Field(default=4096, ge=1)


class DeliveryResult(BaseModel):
    """Outcome of a deliver attempt."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    message_ids: list[int] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list)  # final prepared segments
    actual_delay_seconds: float = 0.0
    typing_duration_seconds: float = 0.0
    error: str | None = None
    cancelled: bool = False

    def to_trace_dict(self) -> dict:
        return self.model_dump(mode="json")


class VipInboundMessage(BaseModel):
    """Application DTO for an inbound VIP business message."""

    model_config = ConfigDict(extra="forbid")

    chat_id: int
    text: str
    telegram_message_id: int | None = None
    business_connection_id: str | None = None
    vip_id: UUID | None = None


class VipRecord(BaseModel):
    """VIP allowlist row shape."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    telegram_user_id: int
    display_name: str | None = None
    is_active: bool = True
    paused_until: datetime | None = None
    frozen_until: datetime | None = None
    auto_send: bool = False


@runtime_checkable
class VipStore(Protocol):
    """VIP allowlist store used by Auth middleware and admin commands."""

    async def get_by_telegram_user_id(
        self, telegram_user_id: int
    ) -> VipRecord | None: ...

    async def is_allowed(
        self, telegram_user_id: int, *, now: datetime | None = None
    ) -> bool:
        """True iff VIP exists, is_active, and not paused (paused_until is None or < now)."""
        ...

    async def add(
        self, telegram_user_id: int, *, display_name: str | None = None
    ) -> VipRecord: ...

    async def deactivate(self, telegram_user_id: int) -> bool:
        """Soft-remove: set is_active=False. Returns False if unknown."""
        ...

    async def get_by_id(self, vip_id: UUID) -> VipRecord | None:
        """Lookup VIP by UUID primary key."""
        ...

    async def freeze_vip(self, vip_id: UUID, frozen_until: datetime) -> None:
        """Set frozen_until column. Raises ValueError if VIP not found."""
        ...

    async def unfreeze_vip(self, vip_id: UUID) -> None:
        """Clear frozen_until column (set to NULL). Raises ValueError if VIP not found."""
        ...

    async def list_active(self) -> list[VipRecord]:
        """Active VIPs only (is_active True), ordered by telegram_user_id ASC."""
        ...

    async def rename(
        self, telegram_user_id: int, display_name: str
    ) -> VipRecord | None:
        """Set display_name for an active VIP. None if missing or inactive. Never reactivates."""
        ...


@runtime_checkable
class OwnerNotifierPort(Protocol):
    """Notify the owner via DM. Never accepts aiogram types."""

    async def notify_draft(self, payload: DraftNotification) -> int | None: ...

    async def notify_escalation(self, payload: EscalationNotification) -> None: ...

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None: ...

    async def notify_doctrine(
        self, payload: DoctrineNotification
    ) -> int | None: ...


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

    async def claim_waiting(self, turn_id: UUID) -> ApprovalRecord | None:
        """CAS: waiting → claimed. Returns claimed record or None if lost race."""
        ...

    async def set_owner_message_id(self, turn_id: UUID, message_id: int) -> None: ...

    async def cancel_waiting_for_chat(self, chat_id: int) -> int: ...

    async def list_waiting(self) -> list[ApprovalRecord]: ...

    async def list_open(self) -> list[ApprovalRecord]:
        """Approvals still in flight: status in {waiting, claimed}."""
        ...


@runtime_checkable
class PendingDeliveryStore(Protocol):
    async def insert_pending(self, record: DeliveryRecord) -> DeliveryRecord: ...

    async def update_status(
        self, delivery_id: UUID, status: str, **meta: Any
    ) -> bool:
        """Conditional status update. Returns False if transition is forbidden."""
        ...

    async def cancel_for_chat(self, chat_id: int) -> int: ...

    async def list_pending(self) -> list[DeliveryRecord]: ...

    async def list_active(self) -> list[DeliveryRecord]:
        """Rows in pending or delivering (for recovery)."""
        ...

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
    """Minimal cancel surface for TurnCoordinator (avoids circular import)."""

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None: ...


@runtime_checkable
class BehaviorDeliverer(Protocol):
    """Deliver gate used by Admin (decoupled from concrete BehaviorEngine)."""

    async def deliver(
        self,
        texts: list[str],
        ctx: Any,
        turn_id: UUID,
        decision: Any | None = None,
    ) -> Any: ...


@runtime_checkable
class TraceabilityReader(Protocol):
    """Read-only trace access for the AdminTraceService.

    Implementations retrieve pipeline trace data from the underlying store
    without modifying it. Returns plain dicts to avoid coupling the protocol
    to ORM or DTO types.
    """

    async def get_recent_turns(self, limit: int = 10, offset: int = 0, chat_id: int | None = None) -> list[dict]: ...
    async def get_full_trace(self, turn_id: UUID) -> dict | None: ...
    async def count_recent(self, chat_id: int | None = None) -> int: ...


@runtime_checkable
class TrainingModeStore(Protocol):
    """Training mode flag for AuthMiddleware gate and config toggle.

    When True, non-VIP business messages pass through the cognitive pipeline
    without VIP attribution (no vip_id/vip_record set in data).
    """

    async def is_enabled(self) -> bool: ...
    async def set_enabled(self, enabled: bool) -> None: ...


# --- F3 proactivity (recontact + promo) ports ---------------------------------


class RecontactScheduleRecord(BaseModel):
    """recontact_schedules row shape.

    Status domain: pending | done | cancelled.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    vip_id: UUID
    last_contact_at: datetime
    next_contact_at: datetime | None = None
    status: str


class PromoTriggerRecord(BaseModel):
    """promo_triggers row shape (exact-match text + sequence + re-intro)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    trigger_text: str
    response_sequence: list[str]
    repeat_first_message: str | None = None
    is_active: bool = True


class PromoExecutionRecord(BaseModel):
    """promo_executions row shape.

    Status domain: sent | failed.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    chat_id: int
    trigger_id: UUID
    sent_at: datetime
    sequence_sent: list[str] | dict | None = None
    status: str


@runtime_checkable
class RecontactScheduleStore(Protocol):
    """CRUD/query surface for VIP recontact schedules (no eligibility logic)."""

    async def upsert_pending(
        self,
        vip_id: UUID,
        last_contact_at: datetime,
        next_contact_at: datetime | None,
    ) -> RecontactScheduleRecord: ...

    async def get_pending_by_vip(
        self, vip_id: UUID
    ) -> RecontactScheduleRecord | None: ...

    async def list_due(self, now: datetime) -> list[RecontactScheduleRecord]:
        """Pending rows with next_contact_at <= now."""
        ...

    async def cancel_pending(self, vip_id: UUID) -> bool:
        """pending → cancelled for vip. False if none pending."""
        ...

    async def mark_done(self, schedule_id: UUID) -> bool:
        """Mark schedule done by id. False if not found."""
        ...


@runtime_checkable
class PromoTriggerStore(Protocol):
    """Active promo trigger lookup.

    Match is exact and case-insensitive (strip + lower) against trigger_text.
    """

    async def get_active_by_trigger_text(
        self, text: str
    ) -> PromoTriggerRecord | None: ...

    async def list_active(self) -> list[PromoTriggerRecord]: ...


@runtime_checkable
class PromoExecutionStore(Protocol):
    """Promo delivery history (thin insert/query only)."""

    async def insert(
        self,
        chat_id: int,
        trigger_id: UUID,
        sequence_sent: list[str] | None,
        status: str = "sent",
    ) -> PromoExecutionRecord: ...

    async def latest_for_chat_trigger(
        self, chat_id: int, trigger_id: UUID
    ) -> PromoExecutionRecord | None: ...

    async def was_sent_since(
        self, chat_id: int, trigger_id: UUID, since: datetime
    ) -> bool:
        """True if a status=sent execution exists with sent_at >= since."""
        ...


__all__ = [
    "ApprovalRecord",
    "BehaviorCanceller",
    "BehaviorDeliverer",
    "DeliveryContext",
    "DeliveryMode",
    "DeliveryRecord",
    "DeliveryResult",
    "DeliveryResultWriter",
    "DoctrineNotification",
    "DraftNotification",
    "EscalationNotification",
    "EscalationStore",
    "GrayZoneQueryView",
    "GrayZoneServicePort",
    "MessageHistoryWriter",
    "OwnerNotifierPort",
    "PendingApprovalStore",
    "PendingDeliveryStore",
    "PromoExecutionRecord",
    "PromoExecutionStore",
    "PromoTriggerRecord",
    "PromoTriggerStore",
    "RecontactScheduleRecord",
    "RecontactScheduleStore",
    "TraceabilityReader",
    "TraceReader",
    "TrainingModeStore",
    "TurnRecord",
    "TurnStore",
    "VipInboundMessage",
    "VipRecord",
    "VipStore",
]
