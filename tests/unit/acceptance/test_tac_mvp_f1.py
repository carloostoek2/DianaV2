"""Automatable TAC / MVP F1 acceptance mapping.

Manual-only (do not block unit gate): live Telegram Business smoke,
kill -9 + real Postgres recovery.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, User

from diana.application.admin_service import AdminService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryMessageHistoryWriter,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
    InMemoryVipStore,
)
from diana.application.ports import VipInboundMessage
from diana.application.recovery_startup import run_startup_recovery
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn
from diana.learning.post_turn import LearningService
from diana.telegram.actuator import AiogramTelegramActuator
from diana.telegram.handlers.business import handle_business_message
from diana.telegram.handlers.callbacks import (
    CorrectSessionStore,
    dispatch_owner_callback,
)
from diana.telegram.keyboards import encode_callback
from diana.telegram.middlewares.auth import AuthMiddleware
from diana.telegram.middlewares.forbidden import ForbiddenKeywordsMiddleware
from diana.telegram.setup import registered_middleware_names

OWNER = 999001
REPO = Path(__file__).resolve().parents[3]


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
    def __init__(self) -> None:
        self.calls = 0

    async def handle_turn(self, turn: IncomingTurn) -> Decision:
        self.calls += 1
        return Decision(
            action="approve",
            reason="ok",
            evaluation=_eval(),
            draft_text="draft reply",
        )


def _compose() -> dict:
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
        owner_telegram_id=OWNER,
    )
    director = FakeDirector()
    learning = LearningService(traces)
    # seed full TRACE_KEYS for learning completeness (optional)
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learning,
        history=history,
    )
    return {
        "orchestrator": orch,
        "admin": admin,
        "director": director,
        "actuator": actuator,
        "notifier": notifier,
        "coordinator": coordinator,
        "approvals": approvals,
        "deliveries": deliveries,
        "escalations": escalations,
        "turns": turns,
        "vips": InMemoryVipStore(),
        "sessions": CorrectSessionStore(),
    }


# --- MVP-01 / no auto-send ---
@pytest.mark.asyncio
async def test_mvp01_no_send_until_approve() -> None:
    g = _compose()
    await g["orchestrator"].handle_vip_message(
        VipInboundMessage(
            chat_id=42,
            text="hola",
            telegram_message_id=1,
            business_connection_id="bc-1",
            vip_id=None,
        )
    )
    assert g["actuator"].send_count() == 0
    assert g["director"].calls == 1
    waiting = await g["approvals"].list_waiting()
    assert len(waiting) == 1
    turn_id = waiting[0].turn_id
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn_id),
        actor_id=OWNER,
    )
    assert status == "approved"
    assert g["actuator"].send_count() >= 1


# --- MVP-02 BC required on send ---
@pytest.mark.asyncio
async def test_mvp02_actuator_requires_bc() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    act = AiogramTelegramActuator(bot)
    with pytest.raises(ValueError, match="business_connection_id"):
        await act.send_message(1, "x", business_connection_id="  ")


# --- MVP-05 / TAC-06 forbidden ---
@pytest.mark.asyncio
async def test_mvp05_tac06_forbidden_zero_director() -> None:
    g = _compose()
    mw = ForbiddenKeywordsMiddleware(
        keywords=["encuentro"],
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
    )
    event = Message(
        message_id=9,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=100, is_bot=False, first_name="V"),
        text="busco encuentro",
        business_connection_id="bc-1",
    )
    handler = AsyncMock()
    await mw(handler, event, {"business_connection_id": "bc-1"})
    handler.assert_not_awaited()
    assert g["director"].calls == 0
    assert g["notifier"].escalations
    assert g["actuator"].send_count() == 0


# --- MVP-06 / TAC-08 recovery ---
@pytest.mark.asyncio
async def test_mvp06_tac08_recovery_no_auto_approve() -> None:
    g = _compose()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    d = await g["deliveries"].insert_pending(
        __import__("diana.application.ports", fromlist=["DeliveryRecord"]).DeliveryRecord(
            id=uuid4(),
            chat_id=1,
            business_connection_id="bc",
            texts=["t"],
            decision={},
            scheduled_at=now,
            status="pending",
            turn_id=uuid4(),
        )
    )
    await g["deliveries"].update_status(d.id, "delivering")
    turn = await g["coordinator"].begin_turn(chat_id=1)
    await g["approvals"].create_waiting(
        __import__("diana.application.ports", fromlist=["ApprovalRecord"]).ApprovalRecord(
            id=uuid4(),
            turn_id=turn.id,
            chat_id=1,
            business_connection_id="bc",
            draft_text="d",
            status="waiting",
        )
    )
    report = await run_startup_recovery(
        deliveries=g["deliveries"],
        approvals=g["approvals"],
        notifier=g["notifier"],
        clock=ImmediateClock(now=now),
        stale_after=timedelta(minutes=30),
    )
    assert report.re_notified_approvals == 1
    stored = await g["approvals"].get_by_turn(turn.id)
    assert stored is not None and stored.status == "waiting"
    assert g["actuator"].send_count() == 0
    got = await g["deliveries"].get(d.id)
    assert got is not None and got.status == "expired"


# --- MVP-08 / TAC-01 purity ---
def test_mvp08_tac01_purity_trio() -> None:
    roots = {
        "cognitive": REPO / "src" / "diana" / "cognitive",
        "application": REPO / "src" / "diana" / "application",
        "behavior": REPO / "src" / "diana" / "behavior",
    }
    for name, root in roots.items():
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                mods: list[str] = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for mod in mods:
                    assert not (mod == "aiogram" or mod.startswith("aiogram.")), (
                        f"{name}/{path.name} imports {mod}"
                    )
                    if name == "cognitive":
                        assert not (
                            mod == "diana.telegram" or mod.startswith("diana.telegram.")
                        ), f"cognitive imports telegram: {path.name}"


# --- Auth allowlist ---
@pytest.mark.asyncio
async def test_auth_non_vip_never_reaches_orchestrator() -> None:
    vips = InMemoryVipStore()
    mw = AuthMiddleware(vips=vips)
    handler = AsyncMock(return_value="orch")
    event = Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=999, is_bot=False, first_name="X"),
        text="hola",
        business_connection_id="bc",
    )
    result = await mw(handler, event, {"business_connection_id": "bc"})
    assert result is None
    handler.assert_not_awaited()


def test_f1_middleware_order_acceptance() -> None:
    from unittest.mock import AsyncMock, MagicMock

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
    from diana.telegram.setup import (
        build_dispatcher,
        extract_observer_middleware_names,
        registered_middleware_names,
    )

    names = registered_middleware_names()
    assert names[0] == "ErrorHandlerMiddleware"
    assert names[6] == "FreezeCheckMiddleware"
    assert names[-2] == "AuthMiddleware"
    assert names[-1] == "ForbiddenKeywordsMiddleware"

    deliveries = InMemoryPendingDeliveryStore()
    behavior = BehaviorEngine(
        FakeTelegramActuator(),
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    wiring = build_dispatcher(
        orchestrator=MagicMock(handle_vip_message=AsyncMock()),
        admin=MagicMock(
            handle_approve=AsyncMock(),
            handle_correct=AsyncMock(),
            handle_owner_escalate=AsyncMock(return_value=True),
            is_pending_approval=AsyncMock(return_value=True),
            _assert_owner=MagicMock(),
        ),
        coordinator=TurnCoordinator(
            InMemoryTurnStore(), InMemoryPendingApprovalStore(), behavior
        ),
        escalations=InMemoryEscalationStore(),
        notifier=FakeOwnerNotifier(),
        behavior=behavior,
        vips=InMemoryVipStore(),
        owner_telegram_id=OWNER,
        forbidden_keywords=[],
    )
    live = extract_observer_middleware_names(wiring.dispatcher.business_message)
    assert live == names


@pytest.mark.asyncio
async def test_business_handler_calls_orchestrator_once() -> None:
    g = _compose()
    tid = await handle_business_message(
        orchestrator=g["orchestrator"],
        chat_id=42,
        text="hi",
        telegram_message_id=3,
        business_connection_id="bc-1",
        vip_id=None,
    )
    assert tid is not None
    assert g["director"].calls == 1
    assert g["actuator"].send_count() == 0
