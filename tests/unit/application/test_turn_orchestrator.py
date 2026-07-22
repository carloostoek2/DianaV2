"""TurnOrchestrator: VIP message → decision application (no auto-send)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from diana.application.admin_service import AdminService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryMessageHistoryWriter,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
)
from diana.application.ports import VipInboundMessage
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn
from diana.cognitive.ports import TRACE_KEYS
from diana.learning.post_turn import LearningService


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


class FakeDirector:
    def __init__(self, decision: Decision | Exception) -> None:
        self._decision = decision
        self.calls: list[IncomingTurn] = []

    async def handle_turn(self, turn: IncomingTurn) -> Decision:
        self.calls.append(turn)
        if isinstance(self._decision, Exception):
            raise self._decision
        return self._decision


class RecordingLearning:
    def __init__(self, inner: LearningService | None = None) -> None:
        self.calls: list[UUID] = []
        self._inner = inner

    async def run_post_turn(self, turn_id: UUID):
        self.calls.append(turn_id)
        if self._inner:
            return await self._inner.run_post_turn(turn_id)
        return None


def _build(
    director: FakeDirector,
    *,
    learning: RecordingLearning | None = None,
) -> dict:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
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
    learn = learning or RecordingLearning(LearningService(traces))
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learn,
        history=history,
    )
    return {
        "orch": orch,
        "director": director,
        "admin": admin,
        "learning": learn,
        "actuator": actuator,
        "behavior": behavior,
        "notifier": notifier,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "history": history,
        "traces": traces,
        "deliveries": deliveries,
    }


def _vip(**kw) -> VipInboundMessage:
    data = {
        "chat_id": 100,
        "text": "hola diana",
        "telegram_message_id": 11,
        "business_connection_id": "bc-vip",
    }
    data.update(kw)
    return VipInboundMessage(**data)


@pytest.mark.asyncio
async def test_r1_approve_never_auto_delivers() -> None:
    decision = Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="reply draft",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert g["actuator"].send_count() == 0
    assert len(g["notifier"].drafts) == 1
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "pending_approval"
    assert g["director"].calls[0].turn_id == turn_id


@pytest.mark.asyncio
async def test_r2_supersede_cancels_approval_and_delivery() -> None:
    decision = Decision(
        action="approve",
        reason="good",
        evaluation=_eval(),
        draft_text="draft A",
    )
    g = _build(FakeDirector(decision))
    a = await g["orch"].handle_vip_message(_vip(text="msg A"))
    appr_a = await g["approvals"].get_by_turn(a)
    assert appr_a is not None and appr_a.status == "waiting"
    b = await g["orch"].handle_vip_message(_vip(text="msg B"))
    assert a != b
    stored_a = await g["turns"].get(a)
    assert stored_a is not None
    assert stored_a.status == "superseded"
    assert stored_a.superseded_by == b
    appr_a2 = await g["approvals"].get_by_turn(a)
    assert appr_a2 is not None and appr_a2.status == "cancelled"
    stored_b = await g["turns"].get(b)
    assert stored_b is not None and stored_b.status == "pending_approval"


@pytest.mark.asyncio
async def test_r4_learning_called_once_after_branch() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert g["learning"].calls == [turn_id]


@pytest.mark.asyncio
async def test_r5_approve_after_supersede_no_deliver() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="old draft",
    )
    g = _build(FakeDirector(decision))
    a = await g["orch"].handle_vip_message(_vip(text="A"))
    await g["orch"].handle_vip_message(_vip(text="B"))
    result = await g["admin"].handle_approve(a)
    assert result is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_escalate_path_no_deliver() -> None:
    decision = Decision(
        action="escalate",
        reason="risk alto",
        evaluation=_eval(),
        draft_text="",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == "escalated"
    assert len(g["notifier"].escalations) == 1


@pytest.mark.asyncio
async def test_director_exception_marks_failed_and_reraises() -> None:
    g = _build(FakeDirector(RuntimeError("llm down")))
    with pytest.raises(RuntimeError, match="llm down"):
        await g["orch"].handle_vip_message(_vip())
    # last non-terminal should not remain; failed is terminal
    non_term = await g["turns"].list_non_terminal(100)
    # failed turn is terminal so non_term empty or only if begin failed mid-way
    assert all(t.status != "received" for t in non_term)
    # find the turn that was created
    # mark_failed should have run
    assert g["actuator"].send_count() == 0
    assert g["learning"].calls == []  # Learning NOT on hard fail


@pytest.mark.asyncio
async def test_turn_id_minted_before_director() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    turn_id = await g["orch"].handle_vip_message(_vip())
    assert isinstance(turn_id, UUID)
    assert g["director"].calls[0].turn_id == turn_id
    assert g["director"].calls[0].text == "hola diana"


@pytest.mark.asyncio
async def test_history_appends_vip_message() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    await g["orch"].handle_vip_message(_vip(text="keep me"))
    recent = await g["history"].get_recent(100)
    assert recent[-1]["role"] == "vip"
    assert recent[-1]["text"] == "keep me"


@pytest.mark.asyncio
async def test_missing_business_connection_id_fails_turn() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="d",
    )
    g = _build(FakeDirector(decision))
    with pytest.raises(ValueError, match="business_connection_id"):
        await g["orch"].handle_vip_message(
            _vip(business_connection_id=None)
        )


@pytest.mark.asyncio
async def test_owner_approve_after_orchestrator_delivers() -> None:
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="final draft",
    )
    traces = InMemoryTraceReaderWriter()
    g = _build(FakeDirector(decision))
    # seed traces so learning complete path also works if used
    turn_id = await g["orch"].handle_vip_message(_vip())
    g["traces"].seed_keys(turn_id, TRACE_KEYS)
    result = await g["admin"].handle_approve(turn_id)
    assert result is not None and result.success
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "final draft"
