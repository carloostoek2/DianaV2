"""Recovery helpers: classify stale vs recoverable pending deliveries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.memory import (
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
)
from diana.application.ports import ApprovalRecord, DeliveryRecord
from diana.application.recovery import (
    classify_pending_deliveries,
    list_waiting_approvals,
)


def _delivery(
    *,
    status: str = "pending",
    scheduled_at: datetime | None = None,
) -> DeliveryRecord:
    return DeliveryRecord(
        id=uuid4(),
        chat_id=1,
        business_connection_id="bc",
        texts=["x"],
        decision={},
        scheduled_at=scheduled_at or datetime.now(UTC),
        status=status,
        turn_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_stale_pending_classified_expired() -> None:
    store = InMemoryPendingDeliveryStore()
    now = datetime.now(UTC)
    stale = _delivery(scheduled_at=now - timedelta(hours=2))
    await store.insert_pending(stale)
    plan = await classify_pending_deliveries(
        store, now=now, stale_after=timedelta(hours=1)
    )
    assert any(d.id == stale.id for d in plan.to_expire)
    assert plan.recoverable == []
    updated = await store.get(stale.id)
    assert updated is not None
    assert updated.status == "expired"


@pytest.mark.asyncio
async def test_fresh_pending_recoverable() -> None:
    store = InMemoryPendingDeliveryStore()
    now = datetime.now(UTC)
    fresh = _delivery(scheduled_at=now - timedelta(minutes=5))
    await store.insert_pending(fresh)
    plan = await classify_pending_deliveries(
        store, now=now, stale_after=timedelta(hours=1)
    )
    assert any(d.id == fresh.id for d in plan.recoverable)
    assert plan.to_expire == []
    still = await store.get(fresh.id)
    assert still is not None and still.status == "pending"


@pytest.mark.asyncio
async def test_cancelled_and_done_ignored() -> None:
    store = InMemoryPendingDeliveryStore()
    now = datetime.now(UTC)
    for status in ("cancelled", "done", "expired"):
        rec = _delivery(status=status, scheduled_at=now - timedelta(hours=5))
        await store.insert_pending(rec)
        await store.update_status(rec.id, status)
    plan = await classify_pending_deliveries(
        store, now=now, stale_after=timedelta(hours=1)
    )
    assert plan.recoverable == []
    assert plan.to_expire == []


@pytest.mark.asyncio
async def test_list_waiting_approvals_only() -> None:
    store = InMemoryPendingApprovalStore()
    waiting_id = uuid4()
    await store.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=waiting_id,
            chat_id=1,
            business_connection_id="bc",
            draft_text="d",
            status="waiting",
        )
    )
    other = uuid4()
    await store.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=other,
            chat_id=2,
            business_connection_id="bc",
            draft_text="d2",
            status="waiting",
        )
    )
    await store.mark_status(other, "approved")
    waiting = await list_waiting_approvals(store)
    assert {a.turn_id for a in waiting} == {waiting_id}
