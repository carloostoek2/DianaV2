"""TAC-06 gold: ForbiddenKeywords → escalate helper; 0 Director/LLM."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
from diana.telegram.middlewares.forbidden import (
    ForbiddenKeywordsMiddleware,
    match_forbidden_keywords,
)


def _graph() -> dict:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    notifier = FakeOwnerNotifier()
    behavior = BehaviorEngine(
        FakeTelegramActuator(),
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    return {
        "coordinator": coordinator,
        "escalations": escalations,
        "notifier": notifier,
        "turns": turns,
        "actuator": behavior._actuator,  # noqa: SLF001
    }


def test_match_forbidden_keywords() -> None:
    hits = match_forbidden_keywords("Quiero un encuentro ya", ["encuentro", "otro"])
    assert hits == ["encuentro"]
    assert match_forbidden_keywords("hola", ["encuentro"]) == []


@pytest.mark.asyncio
async def test_forbidden_match_escalates_without_handler() -> None:
    g = _graph()
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
    )
    # Use a lightweight Message-like that isinstance checks won't pass —
    # so we patch isinstance path by using a real Message mock via SimpleNamespace
    # and temporarily treat via a stub subclass.
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=10,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="V"),
        text="quiero un encuentro",
        business_connection_id="bc-1",
    )
    data: dict = {"business_connection_id": "bc-1"}
    handler = AsyncMock(return_value="orchestrator")
    result = await mw(handler, event, data)
    assert result is None
    handler.assert_not_awaited()
    assert g["escalations"].events
    assert g["notifier"].escalations
    assert g["actuator"].send_count() == 0
    # escalated turn exists
    turns = list(g["turns"]._turns.values())  # noqa: SLF001
    assert any(t.status == "escalated" for t in turns)


@pytest.mark.asyncio
async def test_no_match_passes_to_handler() -> None:
    g = _graph()
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=11,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="V"),
        text="hola todo bien",
        business_connection_id="bc-1",
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, event, {})
    assert result == "next"
    handler.assert_awaited_once()
    assert g["escalations"].events == []
