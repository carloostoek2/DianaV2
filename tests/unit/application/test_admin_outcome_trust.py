"""AdminService → OutcomeLogService C1 trust labels (no coincidence mock)."""

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
    InMemoryVipStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import (
    AlwaysLiveTurnStatusReader,
    FakeTelegramActuator,
    FixedDelayPolicy,
    ImmediateClock,
)
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn

from tests.unit.application.test_outcome_log_service import (
    FakeOutcomeStore,
    FakeTrustBudget,
    _fase_b_service,
    _trace,
)

OWNER_ID = 999001


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


def _admin_graph(*, outcome) -> dict:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    vips = InMemoryVipStore()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=AlwaysLiveTurnStatusReader(),
    )
    from diana.application.approval_ui import ApprovalDraftVoider

    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,  # type: ignore[arg-type]
        approval_ui=ApprovalDraftVoider(notifier),
    )
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,  # type: ignore[arg-type]
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
        delivery_mode="supervised",
        vip_store=vips,  # type: ignore[arg-type]
        outcome=outcome,
        feature_autonomy_readiness_enabled=True,
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "notifier": notifier,
        "actuator": actuator,
        "owner_id": OWNER_ID,
        "outcome": outcome,
    }


def _label_events(trust: FakeTrustBudget) -> list[tuple[str, str]]:
    return [(event, value) for _turn, event, value in trust.calls]


async def _seed_pending(g, *, draft: str, vip_id, outcome):
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, vip_id=vip_id),
        _decision(draft=draft),
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    await outcome.record_shadow(turn.id, vip_id=vip_id, trace=_trace(draft=draft))
    return turn


@pytest.mark.asyncio
async def test_handle_approve_fires_acierto() -> None:
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    g = _admin_graph(outcome=outcome)
    vip_id = uuid4()
    turn = await _seed_pending(g, draft="send me", vip_id=vip_id, outcome=outcome)

    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)

    assert result is not None and result.success is True
    events = _label_events(trust)
    assert ("label", "acierto") in events
    assert ("label", "approved_as_is") not in events


@pytest.mark.asyncio
async def test_handle_correct_fires_desacuerdo() -> None:
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    g = _admin_graph(outcome=outcome)
    vip_id = uuid4()
    turn = await _seed_pending(
        g, draft="original draft", vip_id=vip_id, outcome=outcome
    )

    result = await g["admin"].handle_correct(
        turn.id, "texto corregido", actor_id=OWNER_ID
    )

    assert result is not None and result.success is True
    events = _label_events(trust)
    assert ("label", "desacuerdo") in events
    assert ("label", "corrected") not in events


@pytest.mark.asyncio
async def test_handle_correct_threads_severity_to_owner_outcome() -> None:
    """SPEC-EA-07 (camino B): handle_correct(severity="major") → the outcome
    row persists correction_severity="major" and the trust label event carries
    severity="major"."""
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    g = _admin_graph(outcome=outcome)
    vip_id = uuid4()
    turn = await _seed_pending(
        g, draft="original draft", vip_id=vip_id, outcome=outcome
    )

    result = await g["admin"].handle_correct(
        turn.id, "texto corregido", actor_id=OWNER_ID, severity="major"
    )

    assert result is not None and result.success is True
    assert store.rows[str(turn.id)].correction_severity == "major"
    assert ("label", "desacuerdo") in _label_events(trust)
    assert trust.severities[-1] == "major"


@pytest.mark.asyncio
async def test_handle_approve_passes_no_severity() -> None:
    """SPEC-EA-07: approve never threads severity → no correction_severity on
    the row and the acierto label uses the default moderate (byte-identical)."""
    store = FakeOutcomeStore()
    trust = FakeTrustBudget()
    outcome = _fase_b_service(store, trust)
    g = _admin_graph(outcome=outcome)
    vip_id = uuid4()
    turn = await _seed_pending(g, draft="send me", vip_id=vip_id, outcome=outcome)

    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)

    assert result is not None and result.success is True
    assert store.rows[str(turn.id)].correction_severity is None
    assert ("label", "acierto") in _label_events(trust)
    assert trust.severities[-1] == "moderate"
