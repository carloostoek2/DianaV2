"""Tier-1 fixtures: TurnOrchestrator + AdminService with in-memory stores."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from diana.application.admin_service import AdminService
from diana.application.autonomous_mode_service import AutonomousModeService
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
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.models import Decision, IncomingTurn
from diana.learning.post_turn import LearningService
from diana.telegram.handlers.callbacks import (
    CorrectSessionStore,
    dispatch_owner_callback,
)
from diana.telegram.keyboards import encode_callback

OWNER_ID = 999001
CHAT_ID = 100
VIP_ID = 777001


# ---------------------------------------------------------------------------
# FakeDirector — enqueued decisions, one consumed per handle_turn call
# ---------------------------------------------------------------------------
class FakeDirector:
    def __init__(self, decisions: list[Decision]) -> None:
        self._decisions: list[Decision] = list(decisions)
        self.calls: list[IncomingTurn] = []

    async def handle_turn(self, turn: IncomingTurn) -> Decision:
        self.calls.append(turn)
        if not self._decisions:
            raise RuntimeError("FakeDirector: no more enqueued decisions")
        return self._decisions.pop(0)


# ---------------------------------------------------------------------------
# FakeGrayZone — records queries for consult_doctrine tests
# ---------------------------------------------------------------------------
class FakeGrayZone:
    def __init__(self) -> None:
        self.queries: list[dict] = []
        self._next_id = uuid4()

    async def create_query(
        self, vip_id: UUID, turn_id: UUID, question: str, draft: str, **kwargs
    ) -> object:
        self.queries.append({
            "vip_id": vip_id, "turn_id": turn_id,
            "question": question, "draft": draft,
        })
        return type("_Query", (), {"id": self._next_id})()


# ---------------------------------------------------------------------------
# e2e graph builder — mirrors _build() from test_turn_orchestrator.py
# ---------------------------------------------------------------------------
def build_e2e(
    director_decisions: list[Decision],
    *,
    wire_autonomous: bool = False,
    feature_autonomous_mode: bool = False,
    feature_advanced_behavior: bool = False,
    global_mode: str = "supervised",
    delivery_mode: str = "supervised",
    feature_gray_zone_enabled: bool = False,
    gray_zone: FakeGrayZone | None = None,
    vip_store: InMemoryVipStore | None = None,
    actuator: FakeTelegramActuator | None = None,
    clock: ImmediateClock | None = None,
    delay_policy: FixedDelayPolicy | None = None,
    behavior_override: object | None = None,
) -> dict:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    history = InMemoryMessageHistoryWriter()
    notifier = FakeOwnerNotifier()
    act = actuator or FakeTelegramActuator()
    behavior = behavior_override or BehaviorEngine(
        act, deliveries,
        clock=clock or ImmediateClock(),
        delay_policy=delay_policy or FixedDelayPolicy(),
        feature_advanced_behavior=feature_advanced_behavior,
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)  # type: ignore[arg-type]
    admin = AdminService(
        notifier=notifier, approvals=approvals, escalations=escalations,
        coordinator=coordinator, behavior=behavior,  # type: ignore[arg-type]
        traces=traces, turns=turns,
        owner_telegram_id=OWNER_ID,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        feature_advanced_behavior=feature_advanced_behavior,
    )
    director = FakeDirector(director_decisions)
    learning = LearningService(traces)
    vips = vip_store or InMemoryVipStore()
    ams: AutonomousModeService | None = None
    if wire_autonomous:
        ams = AutonomousModeService(
            feature_autonomous_mode=feature_autonomous_mode,
            global_mode=global_mode,
            vip_store=vips,
            notifier=notifier,
        )
    orch = TurnOrchestrator(
        coordinator=coordinator,
        director=director,  # type: ignore[arg-type]
        admin=admin,
        learning=learning,
        history=history,
        gray_zone=gray_zone,
        feature_gray_zone_enabled=feature_gray_zone_enabled,
        behavior=behavior if wire_autonomous else None,  # type: ignore[arg-type]
        autonomous_mode=ams,
        vip_store=vips if wire_autonomous else None,
        traces=traces if wire_autonomous else None,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        feature_advanced_behavior=feature_advanced_behavior,
        delay_policy=delay_policy,
    )
    sessions = CorrectSessionStore()

    return {
        "orch": orch, "director": director, "admin": admin,
        "notifier": notifier, "actuator": act, "behavior": behavior,
        "turns": turns, "approvals": approvals, "deliveries": deliveries,
        "escalations": escalations, "history": history, "traces": traces,
        "coordinator": coordinator, "vips": vips, "gray_zone": gray_zone,
        "sessions": sessions, "ams": ams,
    }


# ---------------------------------------------------------------------------
# dispatch helper — exercise callback dispatch via data string
# ---------------------------------------------------------------------------
async def dispatch(action: str, turn_id: UUID, g: dict, *, actor_id: int = OWNER_ID) -> str:
    data = encode_callback(action, turn_id)
    return await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=data,
        actor_id=actor_id,
        owner_telegram_id=OWNER_ID,
    )


# ---------------------------------------------------------------------------
# factories
# ---------------------------------------------------------------------------
@pytest.fixture
def vip_msg():
    """Factory for VipInboundMessage with sensible defaults."""
    def _msg(**kw) -> VipInboundMessage:
        defaults = {
            "chat_id": CHAT_ID, "text": "hola diana",
            "telegram_message_id": 11, "business_connection_id": "bc-vip",
        }
        defaults.update(kw)
        return VipInboundMessage(**defaults)
    return _msg
