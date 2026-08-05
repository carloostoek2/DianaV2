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
async def test_startup_cancels_orphan_approvals_with_terminal_turn() -> None:
    """Dead drafts (turn failed/superseded/gone) are cancelled, not re-notified.

    Regression: a crash-recovery orphan approval used to be re-notified on
    every startup with dead buttons ("resuelto o reemplazado" on press).
    """
    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    turns = InMemoryTurnStore()

    live_turn = uuid4()
    failed_turn = uuid4()
    superseded_turn = uuid4()
    gone_turn = uuid4()
    await turns.create(
        TurnRecord(id=live_turn, chat_id=42, status="pending_approval")
    )
    await turns.create(
        TurnRecord(
            id=failed_turn,
            chat_id=42,
            status="failed",
            error="crash_recovery",
        )
    )
    await turns.create(
        TurnRecord(id=superseded_turn, chat_id=42, status="superseded")
    )
    # gone_turn has no turn row at all.

    await approvals.create_waiting(_approval(turn_id=live_turn))
    await approvals.create_waiting(_approval(turn_id=failed_turn))
    await approvals.create_waiting(_approval(turn_id=superseded_turn))
    await approvals.create_waiting(_approval(turn_id=gone_turn))

    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=ImmediateClock(),
        stale_after=timedelta(minutes=30),
        turns=turns,
    )
    assert report.re_notified_approvals == 1
    assert report.orphan_approvals_cancelled == 3
    assert len(notifier.drafts) == 1
    assert notifier.drafts[0].turn_id == live_turn

    live = await approvals.get_by_turn(live_turn)
    assert live is not None and live.status == "waiting"
    for tid in (failed_turn, superseded_turn, gone_turn):
        stored = await approvals.get_by_turn(tid)
        assert stored is not None and stored.status == "cancelled"


@pytest.mark.asyncio
async def test_startup_renotifies_all_when_turns_not_passed() -> None:
    """Backwards compat: without a TurnStore the guard is skipped (re-notify all)."""
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
    assert report.orphan_approvals_cancelled == 0
    assert len(notifier.drafts) == 2


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
async def test_startup_recovers_promo_mid_wait_via_timer() -> None:
    """Restart mid non-VIP promo delay: resume send + execution bookkeeping."""
    from diana.application.memory import InMemoryTurnStore
    from diana.application.ports import DeliveryResult
    from diana.application.promo_service import PROMO_DECISION_KIND, PromoService
    from diana.application.recovery import list_zombie_turns
    from tests.unit.application.test_promo_service import (
        FakeExecutionStore,
        FakePromoConfig,
        FakeSequenceDeliverer,
        FakeTriggerStore,
        _trigger,
    )

    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    timers = InMemoryRuntimeTimerStore()
    turns = InMemoryTurnStore()
    clock = ImmediateClock()
    now = clock.now()

    trig = _trigger(text="info", sequence=["hola", "catalogo"])
    trigger_id = trig.id
    turn_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=9001,
            status="promo_pending",
            vip_id=None,
        )
    )
    delivery = DeliveryRecord(
        id=uuid4(),
        chat_id=9001,
        business_connection_id="bc-promo",
        texts=["hola", "catalogo"],
        decision={
            "kind": PROMO_DECISION_KIND,
            "trigger_id": str(trigger_id),
            "recent": False,
        },
        scheduled_at=now - timedelta(seconds=30),
        status="pending",
        turn_id=turn_id,
        vip_id=None,
    )
    await deliveries.insert_pending(delivery)
    await deliveries.update_status(delivery.id, "delivering")

    timer = RuntimeTimerRecord(
        id=uuid4(),
        chat_id=9001,
        turn_id=turn_id,
        delivery_id=delivery.id,
        scheduled_at=now - timedelta(seconds=30),
        initial_delay_seconds=120.0,
        status="active",
        created_at=now - timedelta(seconds=30),
    )
    await timers.create_active(timer)

    class _PromoBeh:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def deliver(self, **kwargs: object) -> DeliveryResult:
            self.calls.append(dict(kwargs))
            return DeliveryResult(success=True, message_ids=[11, 12])

        async def recover_pending_delivery(self, record, ctx) -> DeliveryResult:
            return DeliveryResult(success=True, message_ids=[1])

    beh = _PromoBeh()
    executions = FakeExecutionStore()
    promo = PromoService(
        feature_promo_enabled=True,
        triggers=FakeTriggerStore([trig]),
        executions=executions,
        config=FakePromoConfig(),
        behavior=FakeSequenceDeliverer(),
        turns=turns,
        clock=clock,
    )

    # Zombies must not kill promo_pending
    zombies = await list_zombie_turns(turns)
    assert all(z.id != turn_id for z in zombies)

    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=clock,
        stale_after=timedelta(minutes=30),
        behavior=beh,
        vips=object(),  # unused for vip_id=None
        global_mode="supervised",
        turns=turns,
        timers=timers,
        promo=promo,
    )

    assert report.timers_recovered == 1
    assert report.promos_recovered == 1
    assert len(beh.calls) == 1
    assert beh.calls[0]["turn_id"] == turn_id
    assert executions.rows and executions.rows[-1].status == "sent"
    turn = await turns.get(turn_id)
    assert turn is not None and turn.status == "delivered"
    old = await deliveries.get(delivery.id)
    assert old is not None and old.status == "expired"
    assert len(await timers.list_active()) == 0
    assert any("promo" in t.lower() for t, _ in notifier.infos)


@pytest.mark.asyncio
async def test_resume_pre_delay_continues_vip_pipeline() -> None:
    """D1: active pre_delay timer resumes waiting_delay into cognitive path."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from diana.application.memory import (
        InMemoryRuntimeTimerStore,
        InMemoryTurnStore,
    )
    from diana.application.ports import RuntimeTimerRecord, TurnRecord, VipInboundMessage
    from diana.application.recovery_startup import resume_pre_delay_timers
    from diana.behavior.fake import ImmediateClock
    from diana.cognitive.models import Decision, EvaluationProfile

    turns = InMemoryTurnStore()
    timers = InMemoryRuntimeTimerStore()
    clock = ImmediateClock(now=datetime(2026, 8, 2, 12, 0, tzinfo=UTC))
    turn_id = uuid4()
    vip_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=100,
            status="waiting_delay",
            vip_id=vip_id,
            trigger_message_id=9,
        )
    )
    now = clock.now()
    await timers.create_active(
        RuntimeTimerRecord(
            id=uuid4(),
            chat_id=100,
            turn_id=turn_id,
            delivery_id=None,
            kind="pre_delay",
            scheduled_at=now - timedelta(seconds=40),
            initial_delay_seconds=120.0,
            status="active",
            created_at=now - timedelta(seconds=40),
            payload={
                "vip_epoch": 2,
                "mode": "supervised",
                "incoming": {
                    "chat_id": 100,
                    "text": "hola vip",
                    "telegram_message_id": 9,
                    "business_connection_id": "bc-1",
                    "vip_id": str(vip_id),
                    "is_edit": False,
                },
            },
        )
    )

    class _Orch:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def resume_waiting_delay(self, **kwargs: object) -> object:
            self.calls.append(dict(kwargs))
            # Simulate pipeline completing after resume.
            await turns.transition(turn_id, "pending_approval")
            return turn_id

    orch = _Orch()
    n = await resume_pre_delay_timers(
        timers=timers,
        turns=turns,
        orchestrator=orch,
        clock=clock,
    )
    assert n == 1
    assert len(orch.calls) == 1
    assert orch.calls[0]["turn_id"] == turn_id
    assert orch.calls[0]["vip_epoch"] == 2
    # ~80s remaining
    assert 79.0 <= float(orch.calls[0]["remaining_seconds"]) <= 81.0
    assert len(await timers.list_active()) == 0
    rec = await turns.get(turn_id)
    assert rec is not None and rec.status == "pending_approval"


@pytest.mark.asyncio
async def test_resume_pre_delay_preserves_atencion_channel() -> None:
    """B4: an atencion turn's channel_type survives a restart — the pre-delay
    payload persists it and recovery resumes the turn on the atencion channel."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from diana.application.memory import (
        InMemoryRuntimeTimerStore,
        InMemoryTurnStore,
    )
    from diana.application.ports import RuntimeTimerRecord, TurnRecord
    from diana.application.recovery_startup import resume_pre_delay_timers
    from diana.behavior.fake import ImmediateClock

    turns = InMemoryTurnStore()
    timers = InMemoryRuntimeTimerStore()
    clock = ImmediateClock(now=datetime(2026, 8, 2, 12, 0, tzinfo=UTC))
    turn_id = uuid4()
    await turns.create(
        TurnRecord(
            id=turn_id,
            chat_id=200,
            status="waiting_delay",
            vip_id=None,
            trigger_message_id=7,
        )
    )
    now = clock.now()
    await timers.create_active(
        RuntimeTimerRecord(
            id=uuid4(),
            chat_id=200,
            turn_id=turn_id,
            delivery_id=None,
            kind="pre_delay",
            scheduled_at=now - timedelta(seconds=40),
            initial_delay_seconds=120.0,
            status="active",
            created_at=now - timedelta(seconds=40),
            payload={
                "vip_epoch": 0,
                "mode": "general",
                "incoming": {
                    "chat_id": 200,
                    "text": "hola atencion",
                    "telegram_message_id": 7,
                    "business_connection_id": "bc-atencion",
                    "vip_id": None,
                    "is_edit": False,
                    "channel_type": "atencion",
                },
            },
        )
    )

    class _Orch:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def resume_waiting_delay(self, **kwargs: object) -> object:
            self.calls.append(dict(kwargs))
            await turns.transition(turn_id, "pending_approval")
            return turn_id

    orch = _Orch()
    n = await resume_pre_delay_timers(
        timers=timers,
        turns=turns,
        orchestrator=orch,
        clock=clock,
    )
    assert n == 1
    incoming = orch.calls[0]["incoming"]
    assert incoming.channel_type == "atencion"
    assert incoming.vip_id is None
    assert incoming.chat_id == 200


@pytest.mark.asyncio
async def test_resume_pre_delay_fails_orphan_waiting_delay() -> None:
    """waiting_delay without timer becomes failed crash_recovery after resume pass."""
    from diana.application.memory import InMemoryRuntimeTimerStore, InMemoryTurnStore
    from diana.application.ports import TurnRecord
    from diana.application.recovery_startup import resume_pre_delay_timers
    from diana.behavior.fake import ImmediateClock

    turns = InMemoryTurnStore()
    timers = InMemoryRuntimeTimerStore()
    turn_id = uuid4()
    await turns.create(
        TurnRecord(id=turn_id, chat_id=5, status="waiting_delay", vip_id=None)
    )
    n = await resume_pre_delay_timers(
        timers=timers,
        turns=turns,
        orchestrator=object(),
        clock=ImmediateClock(),
    )
    assert n == 0
    rec = await turns.get(turn_id)
    assert rec is not None
    assert rec.status == "failed"
    assert rec.error == "crash_recovery"


@pytest.mark.asyncio
async def test_startup_promo_grace_still_delivers() -> None:
    """Promo timers past grace still deliver (unlike VIP delivery timers)."""
    from diana.application.memory import InMemoryTurnStore
    from diana.application.ports import DeliveryResult
    from diana.application.promo_service import PROMO_DECISION_KIND, PromoService
    from tests.unit.application.test_promo_service import (
        FakeExecutionStore,
        FakePromoConfig,
        FakeSequenceDeliverer,
        FakeTriggerStore,
        _trigger,
    )

    deliveries = InMemoryPendingDeliveryStore()
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    timers = InMemoryRuntimeTimerStore()
    turns = InMemoryTurnStore()
    clock = ImmediateClock()
    now = clock.now()
    trig = _trigger()
    turn_id = uuid4()
    await turns.create(
        TurnRecord(id=turn_id, chat_id=7, status="promo_pending", vip_id=None)
    )
    delivery = DeliveryRecord(
        id=uuid4(),
        chat_id=7,
        business_connection_id="bc",
        texts=["a"],
        decision={"kind": PROMO_DECISION_KIND, "trigger_id": str(trig.id)},
        scheduled_at=now - timedelta(hours=2),
        status="pending",
        turn_id=turn_id,
    )
    await deliveries.insert_pending(delivery)
    await deliveries.update_status(delivery.id, "delivering")
    await timers.create_active(
        RuntimeTimerRecord(
            id=uuid4(),
            chat_id=7,
            turn_id=turn_id,
            delivery_id=delivery.id,
            scheduled_at=now - timedelta(hours=2),
            initial_delay_seconds=60.0,
            status="active",
            created_at=now - timedelta(hours=2),
        )
    )

    class _Beh:
        async def deliver(self, **kwargs: object) -> DeliveryResult:
            return DeliveryResult(success=True, message_ids=[1])

    executions = FakeExecutionStore()
    promo = PromoService(
        feature_promo_enabled=True,
        triggers=FakeTriggerStore([trig]),
        executions=executions,
        config=FakePromoConfig(),
        behavior=FakeSequenceDeliverer(),
        turns=turns,
        clock=clock,
    )
    report = await run_startup_recovery(
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        clock=clock,
        timers=timers,
        behavior=_Beh(),
        vips=object(),
        turns=turns,
        promo=promo,
    )
    assert report.timers_recovered == 1
    assert report.promos_recovered == 1
    assert executions.rows[-1].status == "sent"


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
