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


def test_sanitize_forbidden_strips_template_gate_annex_keeps_real_words() -> None:
    from diana.telegram.middlewares.forbidden import (
        TEMPLATE_GATE_OWNED_FORBIDDEN_PHRASES,
        sanitize_forbidden_keywords,
    )

    seed = ["pago", "transferencia", "eres un bot", "reclamación", "eres una ia"]
    cleaned = sanitize_forbidden_keywords(seed)
    assert cleaned == ["pago", "transferencia", "reclamación"]
    for phrase in TEMPLATE_GATE_OWNED_FORBIDDEN_PHRASES:
        assert phrase not in {c.lower() for c in cleaned}


@pytest.mark.asyncio
async def test_legacy_eres_un_bot_in_forbidden_list_passes_to_handler() -> None:
    """H6: annex phrase in seed list is stripped; VIP IA probe reaches handler."""
    g = _graph()
    await g["vips"].add(100, display_name="Vip")
    mw = ForbiddenKeywordsMiddleware(
        keywords=["pago", "transferencia", "eres un bot", "reclamación"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=33,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="V"),
        text="eres un bot?",
        business_connection_id="bc-1",
    )
    handler = AsyncMock(return_value="orchestrator")
    result = await mw(handler, event, {"business_connection_id": "bc-1"})
    assert result == "orchestrator"
    handler.assert_awaited_once()
    assert g["escalations"].events == []


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


# ---------------------------------------------------------------------------
# REQ-ATN-08 — forbidden keywords cover the atencion channel (general mode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atencion_forbidden_hit_when_flag_on() -> None:
    """Flag ON + atencion non-VIP → forbidden check fires and escalates (no VIP)."""
    g = _graph()
    # user 100 is NOT a VIP → is_allowed False
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
        feature_general_mode_enabled=True,
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=50,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Stranger"),
        text="quiero un encuentro",
        business_connection_id="bc-1",
    )
    data: dict = {"business_connection_id": "bc-1", "channel_type": "atencion"}
    handler = AsyncMock(return_value="next")
    result = await mw(handler, event, data)
    assert result is None
    handler.assert_not_awaited()
    assert g["escalations"].events
    assert g["notifier"].escalations
    # atencion has no VIP → the escalated turn carries vip_id None
    turns = list(g["turns"]._turns.values())  # noqa: SLF001
    escalated = [t for t in turns if t.status == "escalated"]
    assert escalated
    assert escalated[0].vip_id is None


@pytest.mark.asyncio
async def test_atencion_forbidden_skip_when_flag_off() -> None:
    """Flag OFF → non-VIP skip fires (byte-identical to today)."""
    g = _graph()
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
        feature_general_mode_enabled=False,
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=51,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Stranger"),
        text="quiero un encuentro",
        business_connection_id="bc-1",
    )
    data: dict = {"business_connection_id": "bc-1", "channel_type": "atencion"}
    handler = AsyncMock(return_value="next")
    result = await mw(handler, event, data)
    assert result == "next"
    handler.assert_awaited_once()
    assert g["escalations"].events == []
    assert g["notifier"].escalations == []


@pytest.mark.asyncio
async def test_vip_forbidden_unchanged() -> None:
    """VIP user forbidden hit → intercepted (unchanged, even with flag ON)."""
    g = _graph()
    await g["vips"].add(100, display_name="Vip")
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
        feature_general_mode_enabled=True,
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=52,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Vip"),
        text="quiero un encuentro",
        business_connection_id="bc-1",
    )
    data: dict = {"business_connection_id": "bc-1", "channel_type": "atencion"}
    handler = AsyncMock(return_value="next")
    result = await mw(handler, event, data)
    assert result is None
    handler.assert_not_awaited()
    assert g["escalations"].events


@pytest.mark.asyncio
async def test_atencion_no_forbidden_keyword_passes() -> None:
    """Flag ON + atencion + clean text → message passes through."""
    g = _graph()
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
        feature_general_mode_enabled=True,
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=53,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Stranger"),
        text="hola buenas tardes",
        business_connection_id="bc-1",
    )
    data: dict = {"business_connection_id": "bc-1", "channel_type": "atencion"}
    handler = AsyncMock(return_value="next")
    result = await mw(handler, event, data)
    assert result == "next"
    handler.assert_awaited_once()
    assert g["escalations"].events == []


@pytest.mark.asyncio
async def test_atencion_j4_only_text_passes_when_flag_on() -> None:
    """REQ-ATN-08: atencion is scoped to forbidden keywords only — a J.4 hit
    (price/identity/commitment) that is NOT a forbidden keyword passes through
    with NO escalation. VIP J.4 classification is unchanged."""
    g = _graph()
    mw = ForbiddenKeywordsMiddleware(
        keywords=["zzz_never"],  # no forbidden keyword hits in the text
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        vips=g["vips"],
        feature_general_mode_enabled=True,
    )
    from aiogram.types import Chat, Message, User

    event = Message(
        message_id=54,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Stranger"),
        text="cuál es el precio?",
        business_connection_id="bc-1",
    )
    data: dict = {"business_connection_id": "bc-1", "channel_type": "atencion"}
    handler = AsyncMock(return_value="next")
    result = await mw(handler, event, data)
    assert result == "next"
    handler.assert_awaited_once()
    assert g["escalations"].events == []
    assert g["notifier"].escalations == []


def test_atencion_explicit_content_seed_rules_present() -> None:
    """REQ-ATN-08: the atencion seed persona carries the anti-explicit hard gate."""
    import json
    import unicodedata
    from pathlib import Path

    import diana

    path = Path(diana.__file__).resolve().parent / "config" / "persona_atencion.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    def _norm(text: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", text.lower())
            if unicodedata.category(c) != "Mn"
        )

    persona = _norm(data["voz_configurada"]["persona"])
    rules = [_norm(r) for r in data["voz_configurada"]["reglas_estilo"]]
    assert "sin contenido explicito" in persona
    assert "intim" in persona  # covers "íntima" (persona) / "íntimo" (reglas)
    assert any("intimo" in r or "explicito" in r or "coqueta" in r for r in rules)
