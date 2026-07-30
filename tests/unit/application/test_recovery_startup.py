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
) -> DeliveryRecord:
    return DeliveryRecord(
        id=uuid4(),
        chat_id=42,
        business_connection_id="bc",
        texts=["x"],
        decision={},
        scheduled_at=scheduled_at or datetime.now(UTC),
        status=status,
        turn_id=uuid4(),
    )


def _approval(turn_id=None) -> ApprovalRecord:
    tid = turn_id or uuid4()
    return ApprovalRecord(
        id=uuid4(),
        turn_id=tid,
        chat_id=42,
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
    mid = mid.model_copy(update={"status": "pending"})
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
    assert report.expired_delivering_or_stale >= 1
    assert report.expired_recoverable >= 1
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
    # All 3 non-terminal turns marked as FAILED
    assert report.zombie_turns_expired == 3
    # Only t1 had generated_text in traces
    assert report.drafts_rematerialized == 1
    # No timers passed
    assert report.timers_recovered == 0

    # Verify t1 was actually rematerialized
    stored = await approvals.get_by_turn(t1.id)
    assert stored is not None
    assert stored.draft_text == "draft from t1"
    assert stored.status == "waiting"


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
