"""F2 middleware registration order — live Dispatcher + ErrorHandler outermost."""

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
from diana.telegram.middlewares import F2_MIDDLEWARE_ORDER
from diana.telegram.setup import (
    build_dispatcher,
    extract_observer_middleware_names,
    middleware_class_names,
    registered_middleware_names,
)


def test_f2_middleware_order_constant() -> None:
    assert registered_middleware_names() == F2_MIDDLEWARE_ORDER
    assert registered_middleware_names() == (
        "ErrorHandlerMiddleware",
        "DedupMiddleware",
        "RateLimitMiddleware",
        "LoggingMiddleware",
        "BusinessConnectionMiddleware",
        "OwnerDetectionMiddleware",
        "FreezeCheckMiddleware",
        "ForbiddenKeywordsMiddleware",
        "AuthMiddleware",
    )


def test_f2_middleware_includes_freeze_check() -> None:
    names = registered_middleware_names()
    assert names[6] == "FreezeCheckMiddleware"


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


def test_build_dispatcher_registers_f2_order_on_business_message() -> None:
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
    assert middleware_class_names(wiring.registered_middlewares) == F2_MIDDLEWARE_ORDER
    live = extract_observer_middleware_names(wiring.dispatcher.business_message)
    assert live == F2_MIDDLEWARE_ORDER
    live_msg = extract_observer_middleware_names(wiring.dispatcher.message)
    assert live_msg == F2_MIDDLEWARE_ORDER
    assert live[0] == "ErrorHandlerMiddleware"
    assert live[1] == "DedupMiddleware"
    assert live[2] == "RateLimitMiddleware"
    assert live_msg[0] == "ErrorHandlerMiddleware"
    assert "FreezeCheckMiddleware" in live
    # Freeze after ErrorHandler + Dedup + RateLimit + Logging + BC + Owner
    assert live[6] == "FreezeCheckMiddleware"

    live_cb = extract_observer_middleware_names(wiring.dispatcher.callback_query)
    assert live_cb[0] == "ErrorHandlerMiddleware"
    assert "DedupMiddleware" in live_cb
    assert "RateLimitMiddleware" in live_cb
    assert "FreezeCheckMiddleware" not in live_cb


def test_build_dispatcher_applies_ops_knobs_to_middleware_instances() -> None:
    """Custom rate/dedup kwargs reach live Dedup + RateLimit instances."""
    from diana.telegram.middlewares.dedup import DedupMiddleware
    from diana.telegram.middlewares.rate_limit import RateLimitMiddleware

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
        rate_limit_max_events=7,
        rate_limit_window_s=3.5,
        dedup_ttl_s=12.0,
    )
    dedup = next(m for m in wiring.registered_middlewares if isinstance(m, DedupMiddleware))
    rate = next(
        m for m in wiring.registered_middlewares if isinstance(m, RateLimitMiddleware)
    )
    assert dedup._ttl_s == 12.0
    assert rate._max_events == 7
    assert rate._window_s == 3.5
    assert rate._owner_telegram_id == 999001
