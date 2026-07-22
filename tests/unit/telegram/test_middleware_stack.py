"""F1 middleware registration order — live Dispatcher + Freeze absent."""

from __future__ import annotations

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
from diana.telegram.middlewares import F1_MIDDLEWARE_ORDER
from diana.telegram.setup import (
    build_dispatcher,
    extract_observer_middleware_names,
    middleware_class_names,
    registered_middleware_names,
)


def test_f1_middleware_order_constant() -> None:
    assert registered_middleware_names() == (
        "LoggingMiddleware",
        "BusinessConnectionMiddleware",
        "OwnerDetectionMiddleware",
        "ForbiddenKeywordsMiddleware",
        "AuthMiddleware",
    )
    assert F1_MIDDLEWARE_ORDER == registered_middleware_names()


def test_freeze_check_absent() -> None:
    names = registered_middleware_names()
    assert not any("Freeze" in n for n in names)


def _fake_orchestrator() -> MagicMock:
    orch = MagicMock()
    orch.handle_vip_message = AsyncMock()
    return orch


def _fake_admin() -> MagicMock:
    admin = MagicMock()
    admin.handle_approve = AsyncMock()
    admin.handle_correct = AsyncMock()
    admin.handle_owner_escalate = AsyncMock(return_value=True)
    admin.is_pending_approval = AsyncMock(return_value=True)
    admin._assert_owner = MagicMock()
    return admin


def test_build_dispatcher_registers_f1_order_on_business_message() -> None:
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
    wiring = build_dispatcher(
        orchestrator=_fake_orchestrator(),
        admin=_fake_admin(),
        coordinator=coordinator,
        escalations=escalations,
        notifier=notifier,
        behavior=behavior,
        vips=InMemoryVipStore(),
        owner_telegram_id=999001,
        forbidden_keywords=["x"],
    )
    assert middleware_class_names(wiring.registered_middlewares) == F1_MIDDLEWARE_ORDER
    live = extract_observer_middleware_names(wiring.dispatcher.business_message)
    assert live == F1_MIDDLEWARE_ORDER
    live_msg = extract_observer_middleware_names(wiring.dispatcher.message)
    assert live_msg == F1_MIDDLEWARE_ORDER
    assert not any("Freeze" in n for n in live)
