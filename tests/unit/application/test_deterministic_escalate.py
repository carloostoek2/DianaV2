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

@pytest.mark.asyncio
async def test_custom_tipo_stored(escalate_graph: dict) -> None:
    g = escalate_graph
    turn_id = await handle_deterministic_escalation(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        chat_id=42,
        text="cuánto cuesta?",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=20,
        keywords_hit=["cuesta"],
        tipo="pago_precio",
    )
    ev = g["escalations"].events[0]
    assert ev["turn_id"] == turn_id
    assert ev["tipo"] == "pago_precio"
    payload = g["notifier"].escalations[0]
    assert payload.tipo == "pago_precio"
    assert "pago_precio" in payload.reason


@pytest.mark.asyncio
async def test_default_tipo_still_palabra_prohibida(escalate_graph: dict) -> None:
    g = escalate_graph
    await handle_deterministic_escalation(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        chat_id=42,
        text="x",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=21,
        keywords_hit=["x"],
    )
    assert g["escalations"].events[0]["tipo"] == "palabra_prohibida"


@pytest.mark.asyncio
async def test_template_escalate_delivers_ia_then_escalates(
    escalate_graph: dict,
) -> None:
    from diana.application.deterministic_escalate import (
        handle_deterministic_template_escalate,
    )
    from diana.application.j4_triggers import IA_TEMPLATE

    g = escalate_graph
    turn_id = await handle_deterministic_template_escalate(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        behavior=g["behavior"],
        chat_id=42,
        text="sos un bot?",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=22,
        keywords_hit=["sos un bot"],
    )
    assert g["actuator"].send_count() == 1
    send_calls = [c for c in g["actuator"].calls if c["op"] == "send_message"]
    assert send_calls[0]["text"] == IA_TEMPLATE
    rec = await g["turns"].get(turn_id)
    assert rec is not None and rec.status == "escalated"
    assert g["escalations"].events[0]["tipo"] == "identidad_ia"
    assert len(g["notifier"].escalations) == 1


@pytest.mark.asyncio
async def test_template_helper_has_no_director_param() -> None:
    import inspect

    from diana.application import deterministic_escalate as mod

    sig = inspect.signature(mod.handle_deterministic_template_escalate)
    names = set(sig.parameters)
    assert "director" not in names
    assert "llm" not in names



@pytest.mark.asyncio
async def test_template_soft_fail_still_escalates(escalate_graph: dict, caplog) -> None:
    """DeliveryResult(success=False) logs and still escalates (never silent)."""
    from unittest.mock import AsyncMock

    from diana.application.deterministic_escalate import (
        handle_deterministic_template_escalate,
    )
    from diana.application.ports import DeliveryResult

    g = escalate_graph
    soft = AsyncMock(
        return_value=DeliveryResult(success=False, error="vip_frozen", cancelled=True)
    )
    behavior = AsyncMock()
    behavior.deliver = soft

    import logging

    with caplog.at_level(logging.WARNING, logger="diana.application"):
        turn_id = await handle_deterministic_template_escalate(
            coordinator=g["coordinator"],
            escalations=g["escalations"],
            notifier=g["notifier"],
            behavior=behavior,
            chat_id=42,
            text="sos un bot?",
            vip_id=None,
            business_connection_id="bc-1",
            message_id=30,
            keywords_hit=["sos un bot"],
        )
    rec = await g["turns"].get(turn_id)
    assert rec is not None and rec.status == "escalated"
    assert g["escalations"].events
    assert g["notifier"].escalations
    msgs = [r.getMessage() for r in caplog.records]
    assert any("soft_fail" in m for m in msgs), msgs


@pytest.mark.asyncio
async def test_template_exception_still_escalates(escalate_graph: dict) -> None:
    from unittest.mock import AsyncMock

    from diana.application.deterministic_escalate import (
        handle_deterministic_template_escalate,
    )

    g = escalate_graph
    behavior = AsyncMock()
    behavior.deliver = AsyncMock(side_effect=RuntimeError("send down"))

    turn_id = await handle_deterministic_template_escalate(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        behavior=behavior,
        chat_id=42,
        text="sos un bot?",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=31,
        keywords_hit=["sos un bot"],
    )
    rec = await g["turns"].get(turn_id)
    assert rec is not None and rec.status == "escalated"
    assert g["escalations"].events[0]["tipo"] == "identidad_ia"
    assert len(g["notifier"].escalations) == 1


@pytest.mark.asyncio
async def test_template_empty_falls_back_to_ia_constant(escalate_graph: dict) -> None:
    from diana.application.deterministic_escalate import (
        handle_deterministic_template_escalate,
    )
    from diana.application.j4_triggers import IA_TEMPLATE

    g = escalate_graph
    await handle_deterministic_template_escalate(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        behavior=g["behavior"],
        chat_id=42,
        text="sos un bot?",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=40,
        keywords_hit=["sos un bot"],
        template="   ",
    )
    send_calls = [c for c in g["actuator"].calls if c["op"] == "send_message"]
    assert send_calls[0]["text"] == IA_TEMPLATE


@pytest.mark.asyncio
async def test_template_hybrid_reason_passed(escalate_graph: dict) -> None:
    from diana.application.deterministic_escalate import (
        handle_deterministic_template_escalate,
    )

    g = escalate_graph
    await handle_deterministic_template_escalate(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        behavior=g["behavior"],
        chat_id=42,
        text="eres bot y precio",
        vip_id=None,
        business_connection_id="bc-1",
        message_id=41,
        keywords_hit=["eres bot", "precio"],
        reason="identidad_ia: eres bot,precio [also: pago_precio]",
    )
    assert "also: pago_precio" in g["notifier"].escalations[0].reason
