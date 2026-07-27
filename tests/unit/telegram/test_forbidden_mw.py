"""TAC-06 gold: ForbiddenKeywords → escalate helper; 0 Director/LLM.

Also: private (owner) DMs must NOT trigger forbidden short-circuit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTurnStore,
    InMemoryVipStore,
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
    vips = InMemoryVipStore()
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
        "approvals": approvals,
        "vips": vips,
        "actuator": behavior._actuator,  # noqa: SLF001
    }


def test_match_forbidden_keywords() -> None:
    hits = match_forbidden_keywords("Quiero un encuentro ya", ["encuentro", "otro"])
    assert hits == ["encuentro"]
    assert match_forbidden_keywords("hola", ["encuentro"]) == []


@pytest.mark.asyncio
async def test_forbidden_match_escalates_without_handler() -> None:
    g = _graph()
    vip = await g["vips"].add(100, display_name="Vip")
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
    )
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
    turns = list(g["turns"]._turns.values())  # noqa: SLF001
    escalated = [t for t in turns if t.status == "escalated"]
    assert escalated
    assert escalated[0].vip_id == vip.id


@pytest.mark.asyncio
async def test_no_match_passes_to_handler() -> None:
    g = _graph()
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
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
    result = await mw(handler, event, {"business_connection_id": "bc-1"})
    assert result == "next"
    handler.assert_awaited_once()
    assert g["escalations"].events == []


@pytest.mark.asyncio
async def test_private_owner_dm_with_keyword_does_not_escalate() -> None:
    """BUG-001: free-text correct / owner private must not hit forbidden."""
    g = _graph()
    # Existing VIP draft pipeline for chat 42
    live = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=1)
    await g["coordinator"].transition(live.id, "pending_approval")
    await g["approvals"].create_waiting(
        __import__("diana.application.ports", fromlist=["ApprovalRecord"]).ApprovalRecord(
            id=__import__("uuid").uuid4(),
            turn_id=live.id,
            chat_id=42,
            business_connection_id="bc-1",
            draft_text="draft",
            status="waiting",
        )
    )

    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
    )
    from aiogram.types import Chat, Message, User

    # Owner private DM (no business_connection_id) containing keyword
    event = Message(
        message_id=99,
        date=0,
        chat=Chat(id=999001, type="private"),
        from_user=User(id=999001, is_bot=False, first_name="Owner"),
        text="quiero un encuentro mañana",
        business_connection_id=None,
    )
    handler = AsyncMock(return_value="admin_handler")
    data: dict = {"is_owner": True}
    result = await mw(handler, event, data)
    assert result == "admin_handler"
    handler.assert_awaited_once()
    assert g["escalations"].events == []
    assert g["notifier"].escalations == []
    # Live VIP turn must not be superseded by private DM
    stored = await g["turns"].get(live.id)
    assert stored is not None and stored.status == "pending_approval"

@pytest.mark.asyncio
async def test_j4_pago_stops_pipeline() -> None:
    """Business VIP J.4 pago → escalate without handler; tipo pago_precio."""
    g = _graph()
    await g["vips"].add(100, display_name="Vip")
    mw = ForbiddenKeywordsMiddleware(
        keywords=["zzz_never"],  # forbidden list empty of real hits
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=30,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="V"),
        text="cuál es el precio?",
        business_connection_id="bc-1",
    )
    handler = AsyncMock(return_value="orchestrator")
    result = await mw(handler, event, {"business_connection_id": "bc-1"})
    assert result is None
    handler.assert_not_awaited()
    assert g["escalations"].events
    assert g["escalations"].events[0]["tipo"] == "pago_precio"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_private_dm_no_j4() -> None:
    """Private owner DM with J.4 keyword must not short-circuit."""
    g = _graph()
    mw = ForbiddenKeywordsMiddleware(
        keywords=[],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=31,
        date=0,
        chat=Chat(id=999001, type="private"),
        from_user=User(id=999001, is_bot=False, first_name="Owner"),
        text="cuál es el precio?",
        business_connection_id=None,
    )
    handler = AsyncMock(return_value="admin")
    result = await mw(handler, event, {"is_owner": True})
    assert result == "admin"
    handler.assert_awaited_once()
    assert g["escalations"].events == []


@pytest.mark.asyncio
async def test_j4_ia_passes_to_handler() -> None:
    """H6: pure IA probe is not middleware short-circuit; handler is awaited."""
    g = _graph()
    await g["vips"].add(100, display_name="Vip")
    from diana.behavior.engine import BehaviorEngine
    from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
    from diana.application.memory import InMemoryPendingDeliveryStore

    actuator = FakeTelegramActuator()
    deliveries = InMemoryPendingDeliveryStore()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    mw = ForbiddenKeywordsMiddleware(
        keywords=[],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
        behavior=behavior,
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=32,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="V"),
        text="eres una ia?",
        business_connection_id="bc-1",
    )
    handler = AsyncMock(return_value="orchestrator")
    result = await mw(handler, event, {"business_connection_id": "bc-1"})
    assert result == "orchestrator"
    handler.assert_awaited_once()
    assert actuator.send_count() == 0
    assert g["escalations"].events == []




@pytest.mark.asyncio
async def test_non_vip_business_j4_does_not_escalate() -> None:
    """VIP store present but user not allowlisted → no escalate/notify."""
    g = _graph()
    # no VIP added for user 100
    mw = ForbiddenKeywordsMiddleware(
        keywords=["zzz"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=40,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Stranger"),
        text="cuál es el precio?",
        business_connection_id="bc-1",
    )
    handler = AsyncMock(return_value="next")
    result = await mw(handler, event, {"business_connection_id": "bc-1"})
    assert result == "next"
    handler.assert_awaited_once()
    assert g["escalations"].events == []
    assert g["notifier"].escalations == []
