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
