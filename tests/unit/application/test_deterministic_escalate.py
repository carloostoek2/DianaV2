"""Deterministic forbidden escalate — zero Director/LLM, no Behavior.deliver."""

from __future__ import annotations

from uuid import UUID

import pytest

from diana.application.deterministic_escalate import handle_deterministic_escalation
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTurnStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock


@pytest.fixture
def escalate_graph() -> dict:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    return {
        "coordinator": coordinator,
        "escalations": escalations,
        "notifier": notifier,
        "actuator": actuator,
        "turns": turns,
        "behavior": behavior,
    }


@pytest.mark.asyncio
async def test_deterministic_escalate_creates_escalated_turn(escalate_graph: dict) -> None:
    g = escalate_graph
    turn_id = await handle_deterministic_escalation(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        chat_id=42,
        text="quiero un encuentro",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=10,
        keywords_hit=["encuentro"],
    )
    assert isinstance(turn_id, UUID)
    rec = await g["turns"].get(turn_id)
    assert rec is not None
    assert rec.status == "escalated"
    assert rec.chat_id == 42
    assert rec.trigger_message_id == 10


@pytest.mark.asyncio
async def test_deterministic_escalate_stores_event_and_notifies(
    escalate_graph: dict,
) -> None:
    g = escalate_graph
    turn_id = await handle_deterministic_escalation(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        chat_id=42,
        text="palabra prohibida x",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=11,
        keywords_hit=["prohibida"],
    )
    assert g["escalations"].events
    ev = g["escalations"].events[0]
    assert ev["turn_id"] == turn_id
    assert ev["tipo"] in {"palabra_prohibida", "forbidden"}
    assert "prohibida" in (ev["motivo"] or "")
    assert ev["notificado"] is True
    assert len(g["notifier"].escalations) == 1
    payload = g["notifier"].escalations[0]
    assert payload.turn_id == turn_id
    assert payload.chat_id == 42


@pytest.mark.asyncio
async def test_deterministic_escalate_never_delivers(escalate_graph: dict) -> None:
    g = escalate_graph
    await handle_deterministic_escalation(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        chat_id=42,
        text="x",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=1,
        keywords_hit=["x"],
    )
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_helper_signature_has_no_director_param() -> None:
    """Gold TAC-06: helper deps exclude Director/LLM by construction."""
    import inspect

    from diana.application import deterministic_escalate as mod

    sig = inspect.signature(mod.handle_deterministic_escalation)
    names = set(sig.parameters)
    assert "director" not in names
    assert "llm" not in names
    assert "cognitive" not in names
