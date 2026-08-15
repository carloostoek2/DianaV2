"""BC lifecycle middleware registration — ErrorHandler + Logging only."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryBusinessConnectionStore,
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
)


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


def test_bc_lifecycle_middleware_is_minimal() -> None:
    """business_connection observer has only ErrorHandler + Logging middleware."""
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
    bc_store = InMemoryBusinessConnectionStore()
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
        bc_store=bc_store,
    )

    live_bc = extract_observer_middleware_names(wiring.dispatcher.business_connection)
    assert live_bc == ("ErrorHandlerMiddleware", "LoggingMiddleware")
    assert "FreezeCheckMiddleware" not in live_bc

    # Other observers must remain unchanged (9-middleware chain).
    live_msg = extract_observer_middleware_names(wiring.dispatcher.business_message)
    assert live_msg[0] == "ErrorHandlerMiddleware"
    assert "FreezeCheckMiddleware" in live_msg


def test_bc_middleware_does_not_affect_main_chain() -> None:
    """Adding BC middleware does not change the main 10-middleware chain."""
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
    bc_store = InMemoryBusinessConnectionStore()
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
        bc_store=bc_store,
    )

    live_msg = extract_observer_middleware_names(wiring.dispatcher.message)
    assert len(live_msg) == 10
    assert live_msg[0] == "ErrorHandlerMiddleware"
    assert live_msg[7] == "FreezeCheckMiddleware"
