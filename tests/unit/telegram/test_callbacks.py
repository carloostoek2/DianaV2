"""Owner callbacks — approve delivers; non-owner denied; no VIP auto-send."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.application.admin_service import AdminService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn
from diana.telegram.handlers.callbacks import (
    CorrectSessionStore,
    dispatch_owner_callback,
)
from diana.telegram.keyboards import encode_callback

OWNER = 999001
OTHER = 111


def _eval() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )


@pytest.fixture
def graph() -> dict:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER,
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "actuator": actuator,
        "sessions": CorrectSessionStore(),
    }


async def _queue_draft(g: dict, draft: str = "hola VIP"):
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text=draft,
    )
    await g["admin"].send_draft_for_approval(
        IncomingTurn(
            turn_id=turn.id,
            chat_id=42,
            text="vip",
            business_connection_id="bc-1",
            telegram_message_id=7,
        ),
        decision,
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    return turn


@pytest.mark.asyncio
async def test_approve_callback_delivers(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OWNER,
    )
    assert status == "approved"
    assert g["actuator"].send_count() >= 1


@pytest.mark.asyncio
async def test_without_approve_no_send(graph: dict) -> None:
    g = graph
    await _queue_draft(g)
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_non_owner_callback_forbidden(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OTHER,
    )
    assert status == "forbidden"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_escalate_callback_no_deliver(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("escalate", turn.id),
        actor_id=OWNER,
    )
    assert status == "escalated"
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "escalated"


@pytest.mark.asyncio
async def test_correct_callback_starts_session_no_deliver(graph: dict) -> None:
    """Correct button only opens FSM; deliver happens later via handle_correct."""
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert status == "awaiting_correct"
    assert g["sessions"].get(OWNER) == turn.id
    assert g["actuator"].send_count() == 0
    # waiting approval still open until free-text correct
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.status == "waiting"


@pytest.mark.asyncio
async def test_correct_callback_non_owner_forbidden(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OTHER,
    )
    assert status == "forbidden"
    assert g["sessions"].get(OTHER) is None
    assert g["sessions"].get(OWNER) is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_approve_after_supersede_returns_stale_replaced(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    await g["coordinator"].begin_turn(chat_id=42)  # supersede
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OWNER,
    )
    assert status == "stale_replaced"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_approve_cancelled_approval_returns_stale_cancelled(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    await g["approvals"].mark_status(turn.id, "cancelled")
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OWNER,
    )
    assert status == "stale_cancelled"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_correct_free_text_delivers(graph: dict) -> None:
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    g = graph
    turn = await _queue_draft(g, draft="original")
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert status == "awaiting_correct"
    result = await handle_admin_text(
        text="corrected with encuentro word ok",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert result == "corrected"
    assert g["actuator"].send_count() >= 1
    assert g["actuator"].calls[-1]["text"] == "corrected with encuentro word ok"
    assert g["sessions"].get(OWNER) is None


@pytest.mark.asyncio
async def test_correct_free_text_after_supersede_stale(graph: dict) -> None:
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    g = graph
    turn = await _queue_draft(g)
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert g["sessions"].get(OWNER) == turn.id
    await g["coordinator"].begin_turn(chat_id=42)  # supersede cancels approval
    g["sessions"].cancel_turn(turn.id)  # supersede invalidates correct FSM
    # Session cleared by cancel_turn; if still set, domain still no-ops honestly.
    g["sessions"].start(OWNER, turn.id)
    result = await handle_admin_text(
        text="too late",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert result == "stale"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_correct_session_timeout(graph: dict) -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock_box = {"t": now}

    def clock() -> datetime:
        return clock_box["t"]

    sessions = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
    g = graph
    g["sessions"] = sessions
    turn = await _queue_draft(g)
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert sessions.get(OWNER) == turn.id
    clock_box["t"] = now + timedelta(minutes=16)
    assert sessions.get(OWNER) is None


def test_correct_session_resolve_live_expired_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from datetime import UTC, datetime, timedelta
    import logging

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock_box = {"t": now}

    def clock() -> datetime:
        return clock_box["t"]

    sessions = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
    turn_id = uuid4()

    # never-started
    assert sessions.resolve(OWNER) == ("none", None)

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        sessions.start(OWNER, turn_id)
    assert any(
        r.getMessage() == "correct_session_started" for r in caplog.records
    )
    state, tid = sessions.resolve(OWNER)
    assert state == "live"
    assert tid == turn_id
    assert sessions.get(OWNER) == turn_id  # resolve live does not consume

    clock_box["t"] = now + timedelta(minutes=16)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        state, expired_id = sessions.resolve(OWNER)
    assert state == "expired"
    assert expired_id == turn_id
    assert sum(1 for r in caplog.records if r.getMessage() == "correct_session_expired") == 1
    # second resolve after expire consume
    assert sessions.resolve(OWNER) == ("none", None)
    assert sessions.get(OWNER) is None


@pytest.mark.asyncio
async def test_handle_admin_text_session_expired_after_ttl(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from datetime import UTC, datetime, timedelta
    import logging
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock_box = {"t": now}

    def clock() -> datetime:
        return clock_box["t"]

    sessions = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
    turn_id = uuid4()
    sessions.start(OWNER, turn_id)
    clock_box["t"] = now + timedelta(minutes=16)

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        result = await handle_admin_text(
            text="too late free text",
            actor_id=OWNER,
            owner_telegram_id=OWNER,
            vips=InMemoryVipStore(),
            admin=None,  # type: ignore[arg-type]
            correct_sessions=sessions,
        )
    assert result == "session_expired"
    assert sessions.get(OWNER) is None
    assert sum(1 for r in caplog.records if r.getMessage() == "correct_session_expired") == 1


@pytest.mark.asyncio
async def test_handle_admin_text_never_started_silent() -> None:
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    sessions = CorrectSessionStore()
    result = await handle_admin_text(
        text="private chatter",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=None,  # type: ignore[arg-type]
        correct_sessions=sessions,
    )
    assert result == "ignored"
    assert result != "session_expired"


@pytest.mark.asyncio
async def test_handle_admin_text_after_cancel_not_session_expired() -> None:
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    sessions = CorrectSessionStore()
    sessions.start(OWNER, uuid4())
    sessions.cancel(OWNER)
    result = await handle_admin_text(
        text="after cancel",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=None,  # type: ignore[arg-type]
        correct_sessions=sessions,
    )
    assert result == "ignored"
