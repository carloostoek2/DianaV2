"""In-memory repository doubles for unit tests (no Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from diana.application.ports import (
    ApprovalRecord,
    BusinessConnectionRecord,
    DeliveryRecord,
    LinkEventRecord,
    RuntimeTimerRecord,
    TurnRecord,
    VipRecord,
)
from diana.cognitive.models import TERMINAL_TURN_STATUSES, TurnStatus, parse_turn_status
from diana.cognitive.ports import to_jsonable

# Approval statuses that supersede must cancel.
_OPEN_APPROVAL_STATUSES = frozenset({"waiting", "claimed"})
OPEN_APPROVAL_STATUSES = _OPEN_APPROVAL_STATUSES

# Delivery status machine (monotonic / cancel-safe). Public alias for SQL adapters.
_DELIVERY_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"delivering", "cancelled", "expired"}),
    "delivering": frozenset({"done", "cancelled", "expired", "error"}),
    "done": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
    "error": frozenset(),
}
DELIVERY_TRANSITIONS = _DELIVERY_TRANSITIONS


def _is_terminal(status: str) -> bool:
    try:
        return parse_turn_status(status) in TERMINAL_TURN_STATUSES
    except ValueError:
        return False


class InMemoryTurnStore:
    """Dict-backed TurnStore with terminal status latch."""

    def __init__(self) -> None:
        self._turns: dict[UUID, TurnRecord] = {}

    async def create(self, turn: TurnRecord) -> TurnRecord:
        self._turns[turn.id] = turn.model_copy(deep=True)
        return self._turns[turn.id].model_copy(deep=True)

    async def get(self, turn_id: UUID) -> TurnRecord | None:
        rec = self._turns.get(turn_id)
        return rec.model_copy(deep=True) if rec else None

    async def list_non_terminal(self, chat_id: int) -> list[TurnRecord]:
        return [
            t.model_copy(deep=True)
            for t in self._turns.values()
            if t.chat_id == chat_id and not _is_terminal(t.status)
        ]

    async def list_all_non_terminal(self) -> list[TurnRecord]:
        return [
            t.model_copy(deep=True)
            for t in self._turns.values()
            if not _is_terminal(t.status)
        ]

    async def transition(
        self,
        turn_id: UUID,
        status: str,
        *,
        superseded_by: UUID | None = None,
        error: str | None = None,
    ) -> TurnRecord:
        rec = self._turns.get(turn_id)
        if rec is None:
            raise KeyError(f"turn not found: {turn_id}")
        new_status = status.value if isinstance(status, TurnStatus) else str(status)

        # Terminal latch: never leave a terminal status (zombie-pipeline guard).
        if _is_terminal(rec.status) and rec.status != new_status:
            return rec.model_copy(deep=True)

        data = rec.model_dump()
        data["status"] = new_status
        # Fix round (R2): mirror SqlTurnStore — the last transition time is
        # the per-turn finalize timestamp used as the extraction upper bound.
        data["updated_at"] = datetime.now(UTC)
        if superseded_by is not None:
            data["superseded_by"] = superseded_by
        if error is not None:
            data["error"] = error
        updated = TurnRecord(**data)
        self._turns[turn_id] = updated
        return updated.model_copy(deep=True)


class InMemoryRuntimeTimerStore:
    """Dict-backed RuntimeTimerStore for unit tests."""

    def __init__(self) -> None:
        self._timers: dict[UUID, RuntimeTimerRecord] = {}

    async def create_active(self, record: RuntimeTimerRecord) -> RuntimeTimerRecord:
        stored = record.model_copy(deep=True)
        self._timers[stored.id] = stored
        return stored.model_copy(deep=True)

    async def mark_completed(self, timer_id: UUID) -> bool:
        rec = self._timers.get(timer_id)
        if rec is None:
            return False
        self._timers[timer_id] = rec.model_copy(update={"status": "completed"})
        return True

    async def list_active(self) -> list[RuntimeTimerRecord]:
        return [
            r.model_copy(deep=True)
            for r in self._timers.values()
            if r.status == "active"
        ]

    async def complete_for_turn(self, turn_id: UUID) -> int:
        n = 0
        for tid, rec in list(self._timers.items()):
            if rec.turn_id == turn_id and rec.status == "active":
                self._timers[tid] = rec.model_copy(update={"status": "completed"})
                n += 1
        return n

    async def delete_for_turn(self, turn_id: UUID) -> None:
        self._timers = {
            k: v for k, v in self._timers.items() if v.turn_id != turn_id
        }

class InMemoryBusinessConnectionStore:
    """Dict-backed BusinessConnectionStore for unit tests."""

    def __init__(self) -> None:
        self._connections: dict[str, BusinessConnectionRecord] = {}

    async def upsert(self, record: BusinessConnectionRecord) -> BusinessConnectionRecord:
        stored = record.model_copy(deep=True)
        self._connections[stored.business_connection_id] = stored
        return stored.model_copy(deep=True)


class InMemoryLinkEventStore:
    """Dict-backed LinkEventStore keyed by event_id for unit tests."""

    def __init__(self) -> None:
        self._events: dict[str, LinkEventRecord] = {}

    async def create(self, record: LinkEventRecord) -> LinkEventRecord:
        if record.event_id in self._events:
            raise ValueError(f"link event already exists: {record.event_id}")
        stored = record.model_copy(deep=True)
        if stored.id is None:
            stored = stored.model_copy(update={"id": uuid4()})
        if stored.created_at is None:
            stored = stored.model_copy(update={"created_at": datetime.now(UTC)})
        self._events[stored.event_id] = stored
        return stored.model_copy(deep=True)

    async def get_by_event_id(self, event_id: str) -> LinkEventRecord | None:
        rec = self._events.get(event_id)
        return rec.model_copy(deep=True) if rec else None

    async def set_state(
        self, event_id: str, state: str, *, decision_at: datetime | None = None
    ) -> None:
        rec = self._events.get(event_id)
        if rec is None:
            raise KeyError(f"link event not found: {event_id}")
        updates: dict[str, Any] = {"state": state}
        if decision_at is not None:
            updates["decision_at"] = decision_at
        self._events[event_id] = rec.model_copy(update=updates)


class InMemoryPendingApprovalStore:
    """Dict-backed PendingApprovalStore keyed by turn_id (CAS claim supported)."""

    def __init__(self) -> None:
        self._by_turn: dict[UUID, ApprovalRecord] = {}

    async def create_waiting(self, record: ApprovalRecord) -> ApprovalRecord:
        if record.turn_id in self._by_turn:
            raise ValueError(f"approval already exists for turn {record.turn_id}")
        stored = record.model_copy(deep=True)
        if stored.status != "waiting":
            stored = stored.model_copy(update={"status": "waiting"})
        self._by_turn[stored.turn_id] = stored
        return stored.model_copy(deep=True)

    async def get_by_turn(self, turn_id: UUID) -> ApprovalRecord | None:
        rec = self._by_turn.get(turn_id)
        return rec.model_copy(deep=True) if rec else None

    async def mark_status(self, turn_id: UUID, status: str) -> None:
        rec = self._by_turn.get(turn_id)
        if rec is None:
            raise KeyError(f"approval not found for turn: {turn_id}")
        self._by_turn[turn_id] = rec.model_copy(update={"status": status})

    async def claim_waiting(self, turn_id: UUID) -> ApprovalRecord | None:
        rec = self._by_turn.get(turn_id)
        if rec is None or rec.status != "waiting":
            return None
        updated = rec.model_copy(update={"status": "claimed"})
        self._by_turn[turn_id] = updated
        return updated.model_copy(deep=True)

    async def set_owner_message_id(self, turn_id: UUID, message_id: int) -> None:
        rec = self._by_turn.get(turn_id)
        if rec is None:
            raise KeyError(f"approval not found for turn: {turn_id}")
        self._by_turn[turn_id] = rec.model_copy(update={"owner_message_id": message_id})

    async def update_draft(
        self,
        turn_id: UUID,
        *,
        draft_text: str,
        evaluation: dict | None = None,
        cognitive_summary: str | None = None,
    ) -> ApprovalRecord | None:
        """CAS: update only while status is ``waiting``. None if missing/raced."""
        rec = self._by_turn.get(turn_id)
        if rec is None or rec.status != "waiting":
            return None
        data: dict[str, Any] = {"draft_text": draft_text}
        if evaluation is not None:
            data["evaluation"] = evaluation
        if cognitive_summary is not None:
            data["cognitive_summary"] = cognitive_summary
        updated = rec.model_copy(update=data)
        self._by_turn[turn_id] = updated
        return updated.model_copy(deep=True)

    async def cancel_waiting_for_chat(self, chat_id: int) -> int:
        count = 0
        for turn_id, rec in list(self._by_turn.items()):
            if rec.chat_id == chat_id and rec.status in _OPEN_APPROVAL_STATUSES:
                self._by_turn[turn_id] = rec.model_copy(update={"status": "cancelled"})
                count += 1
        return count

    async def list_waiting(self) -> list[ApprovalRecord]:
        return [
            r.model_copy(deep=True)
            for r in self._by_turn.values()
            if r.status == "waiting"
        ]

    async def list_open(self) -> list[ApprovalRecord]:
        return [
            r.model_copy(deep=True)
            for r in self._by_turn.values()
            if r.status in _OPEN_APPROVAL_STATUSES
        ]


class InMemoryPendingDeliveryStore:
    """Dict-backed PendingDeliveryStore with monotonic status transitions."""

    def __init__(self) -> None:
        self._items: dict[UUID, DeliveryRecord] = {}

    async def insert_pending(self, record: DeliveryRecord) -> DeliveryRecord:
        stored = record.model_copy(deep=True)
        self._items[stored.id] = stored
        return stored.model_copy(deep=True)

    async def update_status(
        self, delivery_id: UUID, status: str, **meta: Any
    ) -> bool:
        rec = self._items.get(delivery_id)
        if rec is None:
            raise KeyError(f"delivery not found: {delivery_id}")
        _ = meta
        allowed = _DELIVERY_TRANSITIONS.get(rec.status, frozenset())
        if status not in allowed:
            return False
        self._items[delivery_id] = rec.model_copy(update={"status": status})
        return True

    async def cancel_for_chat(self, chat_id: int) -> int:
        count = 0
        for did, rec in list(self._items.items()):
            if rec.chat_id == chat_id and rec.status in {"pending", "delivering"}:
                # Use transition table so cancelled is sticky.
                if "cancelled" in _DELIVERY_TRANSITIONS.get(rec.status, frozenset()):
                    self._items[did] = rec.model_copy(update={"status": "cancelled"})
                    count += 1
        return count

    async def list_pending(self) -> list[DeliveryRecord]:
        return [
            r.model_copy(deep=True)
            for r in self._items.values()
            if r.status == "pending"
        ]

    async def list_active(self) -> list[DeliveryRecord]:
        return [
            r.model_copy(deep=True)
            for r in self._items.values()
            if r.status in {"pending", "delivering"}
        ]

    async def get(self, delivery_id: UUID) -> DeliveryRecord | None:
        rec = self._items.get(delivery_id)
        return rec.model_copy(deep=True) if rec else None

    async def list_all(self) -> list[DeliveryRecord]:
        return [r.model_copy(deep=True) for r in self._items.values()]


class InMemoryEscalationStore:
    """List-backed EscalationStore."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def create(
        self, turn_id: UUID, *, tipo: str, motivo: str | None
    ) -> None:
        self.events.append(
            {
                "turn_id": turn_id,
                "tipo": tipo,
                "motivo": motivo,
                "notificado": False,
            }
        )

    async def mark_notified(self, turn_id: UUID) -> None:
        for ev in self.events:
            if ev["turn_id"] == turn_id:
                ev["notificado"] = True


class InMemoryMessageHistoryWriter:
    """Chat-scoped message history with append + get_recent."""

    def __init__(self) -> None:
        self._messages: dict[int, list[dict]] = {}

    async def append(
        self,
        chat_id: int,
        *,
        role: str,
        text: str,
        telegram_message_id: int | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        entry = {
            "role": role,
            "text": text,
            "telegram_message_id": telegram_message_id,
            "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
        }
        self._messages.setdefault(chat_id, []).append(entry)

    async def upsert_vip_message(
        self,
        chat_id: int,
        *,
        text: str,
        telegram_message_id: int | None,
        timestamp: datetime | None = None,
    ) -> str:
        ts = (timestamp or datetime.now(UTC)).isoformat()
        if telegram_message_id is not None:
            rows = self._messages.setdefault(chat_id, [])
            matched = [
                i
                for i, row in enumerate(rows)
                if row.get("role") == "vip"
                and row.get("telegram_message_id") == telegram_message_id
            ]
            if matched:
                keep = matched[0]
                rows[keep] = {
                    "role": "vip",
                    "text": text,
                    "telegram_message_id": telegram_message_id,
                    "timestamp": ts,
                }
                # Drop accidental duplicates of the same message id.
                for i in reversed(matched[1:]):
                    del rows[i]
                return "updated"
        await self.append(
            chat_id,
            role="vip",
            text=text,
            telegram_message_id=telegram_message_id,
            timestamp=timestamp,
        )
        return "inserted"

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]:
        history = self._messages.get(chat_id, [])
        if limit <= 0:
            return []
        return list(history[-limit:])


class InMemoryTraceReaderWriter:
    """Trace keys + delivery_result for Learning and Admin paths."""

    def __init__(self) -> None:
        self.data: dict[UUID, dict[str, Any]] = {}
        self.delivery_results: dict[UUID, dict] = {}

    async def store(self, turn_id: UUID, key: str, value: Any) -> None:
        bucket = self.data.setdefault(turn_id, {})
        bucket[key] = to_jsonable(value)

    async def set_delivery_result(self, turn_id: UUID, result: dict) -> None:
        self.delivery_results[turn_id] = dict(result)

    async def get_trace_keys(self, turn_id: UUID) -> set[str]:
        return set(self.data.get(turn_id, {}).keys())

    async def get_full_trace(self, turn_id: UUID) -> dict | None:
        bucket = self.data.get(turn_id)
        return dict(bucket) if bucket else None

    async def get_recent_comprehension(
        self,
        chat_id: int,
        *,
        limit: int = 5,
        exclude_turn_id: UUID | None = None,
    ) -> list[dict]:
        """TraceReader protocol completion: no comprehension storage here.

        The in-memory reader has no per-chat comprehension index to query, so
        it returns ``[]`` — the emotional detector hook then sees an empty
        baseline and emits no ``ruptura_de_patron`` signal instead of failing
        with an AttributeError.
        """
        return []

    def get_delivery_result(self, turn_id: UUID) -> dict | None:
        return self.delivery_results.get(turn_id)

    def seed_keys(self, turn_id: UUID, keys: set[str] | list[str]) -> None:
        bucket = self.data.setdefault(turn_id, {})
        for k in keys:
            bucket.setdefault(k, {"seeded": True})


class FakeOwnerNotifier:
    """Records owner notifications for unit assertions."""

    def __init__(self) -> None:
        self.drafts: list[Any] = []
        self.escalations: list[Any] = []
        self.infos: list[tuple[str, int | None]] = []
        self.doctrines: list[Any] = []
        self.voids: list[tuple[int, str]] = []
        self._next_message_id = 5000

    async def notify_draft(self, payload: Any) -> int | None:
        self.drafts.append(payload)
        mid = self._next_message_id
        self._next_message_id += 1
        return mid

    async def notify_escalation(self, payload: Any) -> None:
        self.escalations.append(payload)

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        self.infos.append((text, chat_id))

    async def edit_draft(
        self,
        *,
        owner_message_id: int,
        text: str,
        turn_id: Any,
        chat_id: int,
    ) -> None:
        self.infos.append((f"edit_draft:{owner_message_id}:{text[:40]}", chat_id))

    async def void_draft(self, *, owner_message_id: int, text: str) -> None:
        """Record voided draft DMs (keyboard stripped / no longer applicable)."""
        self.voids.append((owner_message_id, text))

    async def notify_doctrine(self, payload: Any) -> int | None:
        self.doctrines.append(payload)
        mid = self._next_message_id
        self._next_message_id += 1
        return mid


class InMemoryVipStore:
    """Dict-backed VipStore for unit tests and Auth middleware fakes."""

    def __init__(self) -> None:
        self._by_tg: dict[int, VipRecord] = {}
        self._by_id: dict[UUID, VipRecord] = {}

    async def get_by_telegram_user_id(
        self, telegram_user_id: int
    ) -> VipRecord | None:
        rec = self._by_tg.get(telegram_user_id)
        return rec.model_copy(deep=True) if rec else None

    async def get_by_id(self, vip_id: UUID) -> VipRecord | None:
        """Lookup VIP by UUID primary key."""
        rec = self._by_id.get(vip_id)
        return rec.model_copy(deep=True) if rec else None

    async def is_allowed(
        self, telegram_user_id: int, *, now: datetime | None = None
    ) -> bool:
        rec = self._by_tg.get(telegram_user_id)
        if rec is None or not rec.is_active:
            return False
        if rec.paused_until is None:
            return True
        clock = now or datetime.now(UTC)
        paused = rec.paused_until
        if paused.tzinfo is None and clock.tzinfo is not None:
            paused = paused.replace(tzinfo=clock.tzinfo)
        return paused < clock

    async def get_record_and_allowed(
        self,
        telegram_user_id: int,
        *,
        record: VipRecord | None = None,
    ) -> tuple[VipRecord | None, bool]:
        rec = record
        if rec is None:
            rec = self._by_tg.get(telegram_user_id)
        if rec is None:
            return None, False
        if not rec.is_active:
            return rec, False
        if rec.paused_until is None:
            return rec, True
        clock = datetime.now(UTC)
        paused = rec.paused_until
        if paused.tzinfo is None and clock.tzinfo is not None:
            paused = paused.replace(tzinfo=clock.tzinfo)
        return rec, paused < clock

    async def _upsert(self, rec: VipRecord) -> None:
        """Store record in both indexes."""
        self._by_tg[rec.telegram_user_id] = rec
        self._by_id[rec.id] = rec

    async def add(
        self, telegram_user_id: int, *, display_name: str | None = None
    ) -> VipRecord:
        existing = self._by_tg.get(telegram_user_id)
        if existing is not None:
            updated = existing.model_copy(
                update={"is_active": True, "display_name": display_name or existing.display_name}
            )
            await self._upsert(updated)
            return updated.model_copy(deep=True)
        rec = VipRecord(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            display_name=display_name,
            is_active=True,
        )
        await self._upsert(rec)
        return rec.model_copy(deep=True)

    async def deactivate(self, telegram_user_id: int) -> bool:
        rec = self._by_tg.get(telegram_user_id)
        if rec is None:
            return False
        updated = rec.model_copy(update={"is_active": False})
        await self._upsert(updated)
        return True

    async def freeze_vip(self, vip_id: UUID, frozen_until: datetime) -> None:
        """Set frozen_until. Raises ValueError if VIP not found."""
        rec = self._by_id.get(vip_id)
        if rec is None:
            raise ValueError(f"VIP {vip_id} not found")
        updated = rec.model_copy(update={"frozen_until": frozen_until})
        await self._upsert(updated)

    async def unfreeze_vip(self, vip_id: UUID) -> None:
        """Clear frozen_until. Raises ValueError if VIP not found."""
        rec = self._by_id.get(vip_id)
        if rec is None:
            raise ValueError(f"VIP {vip_id} not found")
        updated = rec.model_copy(update={"frozen_until": None})
        await self._upsert(updated)

    async def pause_vip(self, vip_id: UUID, paused_until: datetime) -> None:
        """Set paused_until. Raises ValueError if VIP not found."""
        rec = self._by_id.get(vip_id)
        if rec is None:
            raise ValueError(f"VIP {vip_id} not found")
        updated = rec.model_copy(update={"paused_until": paused_until})
        await self._upsert(updated)

    async def unpause_vip(self, vip_id: UUID) -> None:
        """Clear paused_until. Raises ValueError if VIP not found."""
        rec = self._by_id.get(vip_id)
        if rec is None:
            raise ValueError(f"VIP {vip_id} not found")
        updated = rec.model_copy(update={"paused_until": None})
        await self._upsert(updated)

    async def list_active(self) -> list[VipRecord]:
        """Active VIPs only, ordered by telegram_user_id ASC."""
        active = [r for r in self._by_tg.values() if r.is_active]
        active.sort(key=lambda r: r.telegram_user_id)
        return [r.model_copy(deep=True) for r in active]

    async def rename(
        self, telegram_user_id: int, display_name: str
    ) -> VipRecord | None:
        """Set display_name for an active VIP. None if missing or inactive."""
        rec = self._by_tg.get(telegram_user_id)
        if rec is None or not rec.is_active:
            return None
        updated = rec.model_copy(update={"display_name": display_name})
        await self._upsert(updated)
        return updated.model_copy(deep=True)

    def set_paused_until(
        self, telegram_user_id: int, paused_until: datetime | None
    ) -> None:
        """Test helper: set pause window without a separate port method."""
        rec = self._by_tg.get(telegram_user_id)
        if rec is None:
            raise KeyError(f"vip not found: {telegram_user_id}")
        self._by_tg[telegram_user_id] = rec.model_copy(
            update={"paused_until": paused_until}
        )


__all__ = [
    "DELIVERY_TRANSITIONS",
    "OPEN_APPROVAL_STATUSES",
    "FakeOwnerNotifier",
    "InMemoryEscalationStore",
    "InMemoryMessageHistoryWriter",
    "InMemoryPendingApprovalStore",
    "InMemoryPendingDeliveryStore",
    "InMemoryBusinessConnectionStore",
    "InMemoryLinkEventStore",
    "InMemoryRuntimeTimerStore",
    "InMemoryTraceReaderWriter",
    "InMemoryTurnStore",
    "InMemoryVipStore",
]
