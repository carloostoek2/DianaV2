"""Delivery transition matrix parity — pure table + InMemory gold."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from diana.application.memory import DELIVERY_TRANSITIONS, InMemoryPendingDeliveryStore
from diana.application.ports import DeliveryRecord
from diana.infrastructure.db.repositories.deliveries import can_transition_delivery


def _rec(status: str = "pending") -> DeliveryRecord:
    return DeliveryRecord(
        id=uuid4(),
        chat_id=1,
        business_connection_id="bc",
        texts=["hi"],
        decision={},
        scheduled_at=datetime.now(UTC),
        status=status,
        turn_id=uuid4(),
    )


@pytest.mark.parametrize(
    "current,new,allowed",
    [
        ("pending", "delivering", True),
        ("pending", "cancelled", True),
        ("pending", "expired", True),
        ("pending", "done", False),
        ("delivering", "done", True),
        ("delivering", "cancelled", True),
        ("delivering", "expired", True),
        ("delivering", "error", True),
        ("delivering", "pending", False),
        ("done", "pending", False),
        ("done", "cancelled", False),
        ("cancelled", "pending", False),
        ("expired", "delivering", False),
        ("error", "done", False),
    ],
)
def test_can_transition_delivery_matrix(
    current: str, new: str, allowed: bool
) -> None:
    assert can_transition_delivery(current, new) is allowed
    assert (new in DELIVERY_TRANSITIONS.get(current, frozenset())) is allowed


@pytest.mark.asyncio
async def test_inmemory_illegal_done_to_pending_returns_false() -> None:
    store = InMemoryPendingDeliveryStore()
    rec = _rec("pending")
    await store.insert_pending(rec)
    assert await store.update_status(rec.id, "delivering") is True
    assert await store.update_status(rec.id, "done") is True
    assert await store.update_status(rec.id, "pending") is False
    got = await store.get(rec.id)
    assert got is not None and got.status == "done"
