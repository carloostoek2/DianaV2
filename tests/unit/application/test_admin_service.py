"""AdminService: owner queue gates; no deliver after supersede."""

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
from diana.application.ports import ApprovalRecord
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn


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


def _decision(action: str = "approve", draft: str = "hola VIP") -> Decision:
    return Decision(
        action=action,  # type: ignore[arg-type]
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
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "notifier": notifier,
        "actuator": actuator,
        "behavior": behavior,
        "traces": traces,
        "escalations": escalations,
    }


def _incoming(turn_id, **kw) -> IncomingTurn:
    data = {
        "turn_id": turn_id,
        "chat_id": 42,
        "text": "vip says hi",
        "business_connection_id": "bc-1",
        "telegram_message_id": 7,
    }
    data.update(kw)
    return IncomingTurn(**data)


@pytest.mark.asyncio
async def test_send_draft_for_approval_notifies_and_persists(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    decision = _decision(draft="draft text")
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), decision, turn.id
    )
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].draft_text == "draft text"
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None
    assert appr.status == "waiting"
    assert appr.draft_text == "draft text"


@pytest.mark.asyncio
async def test_handle_approve_delivers_and_marks_delivered(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    decision = _decision(draft="send me")
    await g["admin"].send_draft_for_approval(_incoming(turn.id), decision, turn.id)
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id)
    assert result is not None
    assert result.success is True
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "send me"
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "delivered"
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.status == "approved"
    assert g["traces"].get_delivery_result(turn.id) is not None


@pytest.mark.asyncio
async def test_handle_correct_delivers_corrected_not_draft(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="original draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_correct(turn.id, "corrected final")
    assert result is not None and result.success
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "corrected final"
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.status == "corrected"
    # no staging attribute on admin
    assert not hasattr(g["admin"], "staging")


@pytest.mark.asyncio
async def test_handle_approve_after_supersede_no_deliver(admin_graph: dict) -> None:
    g = admin_graph
    a = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(a.id), _decision(draft="old"), a.id
    )
    await g["coordinator"].transition(a.id, "pending_approval")
    await g["coordinator"].begin_turn(chat_id=42)  # supersede A
    result = await g["admin"].handle_approve(a.id)
    assert result is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_notify_escalation_creates_event(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    decision = _decision(action="escalate", draft=None)
    # Decision requires draft_text optional - escalate can have None
    decision = Decision(
        action="escalate",
        reason="safety",
        evaluation=_eval(),
        draft_text="",
    )
    await g["admin"].notify_escalation(_incoming(turn.id), decision, turn.id)
    assert len(g["notifier"].escalations) == 1
    assert g["escalations"].events
    assert g["escalations"].events[0]["tipo"] == "semantica"


@pytest.mark.asyncio
async def test_send_draft_requires_business_connection_id(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    with pytest.raises(ValueError, match="business_connection_id"):
        await g["admin"].send_draft_for_approval(
            _incoming(turn.id, business_connection_id=None),
            _decision(),
            turn.id,
        )
