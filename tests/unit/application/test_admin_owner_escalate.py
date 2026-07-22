"""AdminService.handle_owner_escalate — cancel approval, no deliver."""

from __future__ import annotations

import pytest

from diana.application.admin_service import AdminService, OwnerAuthError
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

OWNER_ID = 999001
OTHER_USER = 111


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


def _decision(draft: str = "hola") -> Decision:
    return Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text=draft,
    )


@pytest.fixture
def admin_graph() -> dict:
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
        owner_telegram_id=OWNER_ID,
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "notifier": notifier,
        "actuator": actuator,
        "owner_id": OWNER_ID,
    }


def _incoming(turn_id, **kw) -> IncomingTurn:
    data = {
        "turn_id": turn_id,
        "chat_id": 42,
        "text": "vip",
        "business_connection_id": "bc-1",
        "telegram_message_id": 7,
    }
    data.update(kw)
    return IncomingTurn(**data)


@pytest.mark.asyncio
async def test_owner_escalate_cancels_waiting_and_escalates_turn(
    admin_graph: dict,
) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    await g["admin"].handle_owner_escalate(turn.id, actor_id=OWNER_ID)
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None
    assert appr.status == "cancelled"
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "escalated"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_owner_escalate_non_owner_raises(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    with pytest.raises(OwnerAuthError):
        await g["admin"].handle_owner_escalate(turn.id, actor_id=OTHER_USER)
    with pytest.raises(OwnerAuthError):
        await g["admin"].handle_owner_escalate(turn.id, actor_id=None)
    assert g["actuator"].send_count() == 0
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.status == "waiting"


@pytest.mark.asyncio
async def test_owner_escalate_terminal_is_noop(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["coordinator"].transition(turn.id, "escalated")
    await g["admin"].handle_owner_escalate(turn.id, actor_id=OWNER_ID)
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "escalated"
    assert g["actuator"].send_count() == 0
