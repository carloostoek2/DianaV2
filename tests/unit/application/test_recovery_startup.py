"""Startup recovery — expire mid-flight; re-notify only; never deliver/approve."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryRuntimeTimerStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
)
from diana.application.ports import (
    ApprovalRecord,
    DeliveryRecord,
    RuntimeTimerRecord,
    TurnRecord,
)
from diana.application.recovery_startup import run_startup_recovery
from diana.behavior.fake import ImmediateClock


def _delivery(
    *,
    status: str = "pending",
    scheduled_at: datetime | None = None,
    turn_id=None,
) -> DeliveryRecord:
    return DeliveryRecord(
        id=uuid4(),
        chat_id=42,
        business_connection_id="bc",
        texts=["x"],
        decision={},
        scheduled_at=scheduled_at or datetime.now(UTC),
        status=status,
        turn_id=turn_id or uuid4(),
    )


def _approval(turn_id=None, *, chat_id: int = 42) -> ApprovalRecord:
    tid = turn_id or uuid4()
    return ApprovalRecord(
        id=uuid4(),
        turn_id=tid,
        chat_id=chat_id,
        business_connection_id="bc",
        draft_text="draft",
        status="waiting",
    )


@pytest.mark.asyncio
async def test_startup_expires_delivering_and_recoverable() -> None:
    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock = ImmediateClock(now=now)

    mid = _delivery(status="pending")
    await deliveries.insert_pending(mid)
    # force delivering
    await deliveries.update_status(mid.id, "delivering")

    fresh = _delivery(status="pending", scheduled_at=now - timedelta(minutes=1))
    await deliveries.insert_pending(fresh)

    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=clock,
        stale_after=timedelta(minutes=30),
    )
    assert report.expired_delivering_or_stale == 1
    assert report.expired_recoverable == 1
    got_mid = await deliveries.get(mid.id)
    got_fresh = await deliveries.get(fresh.id)
    assert got_mid is not None and got_mid.status == "expired"
    assert got_fresh is not None and got_fresh.status == "expired"
    assert any("re-approve" in t for t, _ in notifier.infos)


@pytest.mark.asyncio
async def test_startup_renotifies_waiting_approvals() -> None:
    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    a1 = _approval()
    a2 = _approval()
    await approvals.create_waiting(a1)
    await approvals.create_waiting(a2)
    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=ImmediateClock(),
        stale_after=timedelta(minutes=30),
    )
    assert report.re_notified_approvals == 2
    assert len(notifier.drafts) == 2
    # still waiting — never auto-approved
    for a in (a1, a2):
        stored = await approvals.get_by_turn(a.turn_id)
        assert stored is not None and stored.status == "waiting"
        # New DM message id persisted so regen/edit targets the fresh message
        assert stored.owner_message_id is not None


@pytest.mark.asyncio
async def test_startup_keeps_pending_approval_turns_approvable() -> None:
    """Owner-waiting drafts survive restart: turn stays pending_approval."""
    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    turns = InMemoryTurnStore()
    turn_id = uuid4()
    await turns.create(
        TurnRecord(id=turn_id, chat_id=42, status="pending_approval")
    )
    await approvals.create_waiting(
        _approval(turn_id=turn_id, chat_id=42)
    )
    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=ImmediateClock(),
        stale_after=timedelta(minutes=30),
        turns=turns,
    )
    assert report.zombie_turns_expired == 0
    assert report.re_notified_approvals == 1
    rec = await turns.get(turn_id)
    assert rec is not None
    assert rec.status == "pending_approval"
    stored = await approvals.get_by_turn(turn_id)
    assert stored is not None and stored.status == "waiting"


@pytest.mark.asyncio
async def test_startup_never_calls_deliver_or_approve() -> None:
    """Guard: recovery helper has no direct approve/Director surface.

    Recovery MAY call BehaviorEngine.recover_pending_delivery to safely
    re-schedule fresh pending deliveries, but must never auto-approve or
    invoke the cognitive pipeline (Director).
    """
    import inspect

    from diana.application import recovery_startup as mod

    src = inspect.getsource(mod.run_startup_recovery)
    assert "handle_approve" not in src
    assert "Director" not in src


@pytest.mark.asyncio
async def test_startup_reports_zombie_and_remat_counters() -> None:
    """When turns+traces are passed, zombie and remat counters are populated."""
    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    turns = InMemoryTurnStore()
    traces = InMemoryTraceReaderWriter()
    clock = ImmediateClock()

    # Create non-terminal turns (all before zombie kill)
    t1 = TurnRecord(id=uuid4(), chat_id=1, status="generating")
    t2 = TurnRecord(id=uuid4(), chat_id=2, status="deciding")
    t3 = TurnRecord(id=uuid4(), chat_id=1, status="analyzing")
    await turns.create(t1)
    await turns.create(t2)
    await turns.create(t3)

    # Seed trace with generated_text for t1 only
    await traces.store(t1.id, "generated_text", "draft from t1")

    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=clock,
        stale_after=timedelta(minutes=30),
        turns=turns,
        traces=traces,
    )
    # t1 rematerialized → pending_approval (not zombie); t2+t3 mid-pipeline failed
    assert report.zombie_turns_expired == 2
    assert report.drafts_rematerialized == 1
    assert report.timers_recovered == 0

    stored = await approvals.get_by_turn(t1.id)
    assert stored is not None
    assert stored.draft_text == "draft from t1"
    assert stored.status == "waiting"
    rec1 = await turns.get(t1.id)
    assert rec1 is not None
    assert rec1.status == "pending_approval"
    # t2/t3 pure zombies
    for tid in (t2.id, t3.id):
        rec = await turns.get(tid)
        assert rec is not None
        assert rec.status == "failed"


@pytest.mark.asyncio
async def test_startup_timer_recovery_marks_expired_timers_completed() -> None:
    """When timers+behavior are passed, timer recovery runs and marks expired timers done."""
    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    timers = InMemoryRuntimeTimerStore()
    clock = ImmediateClock()

    class _MockBehavior:
        async def deliver(self, **kwargs: object) -> None:
            pass

    now = clock.now()
    expired_timer = RuntimeTimerRecord(
        id=uuid4(),
        chat_id=1,
        turn_id=uuid4(),
        delivery_id=uuid4(),
        scheduled_at=now - timedelta(hours=2),
        initial_delay_seconds=60.0,
        status="active",
        created_at=now - timedelta(hours=2),
    )
    await timers.create_active(expired_timer)
    assert len(await timers.list_active()) == 1

    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=clock,
        stale_after=timedelta(minutes=30),
        timers=timers,
        behavior=_MockBehavior(),
        global_mode="supervised",
    )
    # Timer expired (remaining <= 5s grace), not recovered
    assert report.timers_recovered == 0
    # Timer was marked completed by the recovery path
    assert len(await timers.list_active()) == 0
    assert report.zombie_turns_expired == 0
    assert report.drafts_rematerialized == 0


@pytest.mark.asyncio
async def test_startup_without_turns_traces_timers_backwards_compat() -> None:
    """When optional params are not passed, new counters default to 0."""
    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    clock = ImmediateClock()

    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=clock,
        stale_after=timedelta(minutes=30),
    )
    assert report.zombie_turns_expired == 0
    assert report.drafts_rematerialized == 0
    assert report.timers_recovered == 0
    assert report.expired_delivering_or_stale == 0
    assert report.re_notified_approvals == 0


@pytest.mark.asyncio
async def test_startup_timer_recovery_reschedules_active_timer() -> None:
    """Timer with remaining > 5s is re-scheduled: delivery dispatched, old expired, timer completed."""
    from unittest.mock import patch

    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    timers = InMemoryRuntimeTimerStore()
    clock = ImmediateClock()
    now = clock.now()

    class _MockBehavior:
        def __init__(self) -> None:
            self.deliver_calls: list[dict] = []

        async def deliver(self, **kwargs: object) -> None:
            self.deliver_calls.append(kwargs)

    behavior = _MockBehavior()

    # Create a delivery record
    turn_id = uuid4()
    delivery = _delivery(status="pending", turn_id=turn_id)
    delivery = await deliveries.insert_pending(delivery)

    # Create a timer with remaining > 5s (scheduled_at=now, initial_delay=6.0)
    timer = RuntimeTimerRecord(
        id=uuid4(),
        chat_id=1,
        turn_id=turn_id,
        delivery_id=delivery.id,
        scheduled_at=now,
        initial_delay_seconds=6.0,
        status="active",
        created_at=now,
    )
    await timers.create_active(timer)
    assert len(await timers.list_active()) == 1

    # Patch asyncio.sleep to avoid actual waiting during recovery.
    with patch("asyncio.sleep", return_value=None):
        report = await run_startup_recovery(
            deliveries=deliveries,
            approvals=approvals,
            notifier=notifier,
            clock=clock,
            stale_after=timedelta(minutes=30),
            timers=timers,
            behavior=behavior,
            global_mode="supervised",
        )

    assert report.timers_recovered == 1

    # Timer was marked completed.
    assert len(await timers.list_active()) == 0

    # Old delivery was expired.
    expired = await deliveries.get(delivery.id)
    assert expired is not None and expired.status == "expired"

    # behavior.deliver was called with the correct texts/turn_id.
    assert len(behavior.deliver_calls) == 1
    call = behavior.deliver_calls[0]
    assert call["texts"] == list(delivery.texts)
    assert call["turn_id"] == delivery.turn_id
