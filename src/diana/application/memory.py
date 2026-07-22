"""In-memory repository doubles for unit tests (no Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from diana.application.ports import (
    ApprovalRecord,
    DeliveryRecord,
    TurnRecord,
)
from diana.cognitive.models import TERMINAL_TURN_STATUSES, TurnStatus, parse_turn_status
from diana.cognitive.ports import to_jsonable


def _is_terminal(status: str) -> bool:
    try:
        return parse_turn_status(status) in TERMINAL_TURN_STATUSES
    except ValueError:
        return False


class InMemoryTurnStore:
    """Dict-backed TurnStore."""

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
        data = rec.model_dump()
        data["status"] = status.value if isinstance(status, TurnStatus) else str(status)
        if superseded_by is not None:
            data["superseded_by"] = superseded_by
        if error is not None:
            data["error"] = error
        updated = TurnRecord(**data)
        self._turns[turn_id] = updated
        return updated.model_copy(deep=True)


class InMemoryPendingApprovalStore:
    """Dict-backed PendingApprovalStore keyed by turn_id."""

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

    async def cancel_waiting_for_chat(self, chat_id: int) -> int:
        count = 0
        for turn_id, rec in list(self._by_turn.items()):
            if rec.chat_id == chat_id and rec.status == "waiting":
                self._by_turn[turn_id] = rec.model_copy(update={"status": "cancelled"})
                count += 1
        return count

    async def list_waiting(self) -> list[ApprovalRecord]:
        return [
            r.model_copy(deep=True)
            for r in self._by_turn.values()
            if r.status == "waiting"
        ]


class InMemoryPendingDeliveryStore:
    """Dict-backed PendingDeliveryStore."""

    def __init__(self) -> None:
        self._items: dict[UUID, DeliveryRecord] = {}

    async def insert_pending(self, record: DeliveryRecord) -> DeliveryRecord:
        stored = record.model_copy(deep=True)
        self._items[stored.id] = stored
        return stored.model_copy(deep=True)

    async def update_status(
        self, delivery_id: UUID, status: str, **meta: Any
    ) -> None:
        rec = self._items.get(delivery_id)
        if rec is None:
            raise KeyError(f"delivery not found: {delivery_id}")
        updates: dict[str, Any] = {"status": status}
        # meta reserved for future fields; ignore unknown keys on the record
        _ = meta
        self._items[delivery_id] = rec.model_copy(update=updates)

    async def cancel_for_chat(self, chat_id: int) -> int:
        count = 0
        for did, rec in list(self._items.items()):
            if rec.chat_id == chat_id and rec.status in {"pending", "delivering"}:
                self._items[did] = rec.model_copy(update={"status": "cancelled"})
                count += 1
        return count

    async def list_pending(self) -> list[DeliveryRecord]:
        return [
            r.model_copy(deep=True)
            for r in self._items.values()
            if r.status == "pending"
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


__all__ = [
    "FakeOwnerNotifier",
    "InMemoryEscalationStore",
    "InMemoryMessageHistoryWriter",
    "InMemoryPendingApprovalStore",
    "InMemoryPendingDeliveryStore",
    "InMemoryTraceReaderWriter",
    "InMemoryTurnStore",
]
