"""Dispatcher registration — F1 middleware order + routers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiogram import Dispatcher, Router

from diana.application.admin_service import AdminService
from diana.application.ports import (
    BehaviorCanceller,
    EscalationStore,
    OwnerNotifierPort,
    VipStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.telegram.handlers.admin import build_admin_router
from diana.telegram.handlers.business import build_business_router
from diana.telegram.handlers.callbacks import (
    CorrectSessionStore,
    build_callback_router,
)
from diana.telegram.middlewares import F1_MIDDLEWARE_ORDER
from diana.telegram.middlewares.auth import AuthMiddleware
from diana.telegram.middlewares.business_connection import BusinessConnectionMiddleware
from diana.telegram.middlewares.forbidden import ForbiddenKeywordsMiddleware
from diana.telegram.middlewares.logging import LoggingMiddleware
from diana.telegram.middlewares.owner import OwnerDetectionMiddleware


@dataclass
class TelegramWiring:
    """Built dispatcher + ordered middleware class names for tests."""

    dispatcher: Dispatcher
    middleware_order: tuple[str, ...]
    correct_sessions: CorrectSessionStore
    forbidden_middleware: ForbiddenKeywordsMiddleware
    registered_middlewares: list[Any]


def middleware_class_names(middlewares: list[Any]) -> tuple[str, ...]:
    """Extract class names from registered middleware instances."""
    return tuple(type(m).__name__ for m in middlewares)


def extract_observer_middleware_names(observer: Any) -> tuple[str, ...]:
    """Read live MiddlewareManager registration order (first = outermost)."""
    manager = getattr(observer, "middleware", None)
    if manager is None:
        return ()
    chain = getattr(manager, "_middlewares", None) or []
    names: list[str] = []
    for item in chain:
        mw = item[0] if isinstance(item, tuple) else item
        names.append(type(mw).__name__)
    return tuple(names)


def build_dispatcher(
    *,
    orchestrator: TurnOrchestrator,
    admin: AdminService,
    coordinator: TurnCoordinator,
    escalations: EscalationStore,
    notifier: OwnerNotifierPort,
    behavior: BehaviorCanceller,
    vips: VipStore,
    owner_telegram_id: int,
    forbidden_keywords: list[str],
    correct_sessions: CorrectSessionStore | None = None,
) -> TelegramWiring:
    """Register F1 middleware order and thin routers."""
    dp = Dispatcher()
    sessions = correct_sessions or CorrectSessionStore()

    # first registered = outermost (aiogram wraps with reversed()).
    # F1 execution order: Logging → BC → Owner → Forbidden → Auth → handler.
    forbidden_mw = ForbiddenKeywordsMiddleware(
        keywords=forbidden_keywords,
        coordinator=coordinator,
        escalations=escalations,
        notifier=notifier,
        vips=vips,
    )
    middlewares: list[Any] = [
        LoggingMiddleware(),
        BusinessConnectionMiddleware(),
        OwnerDetectionMiddleware(
            owner_telegram_id=owner_telegram_id, behavior=behavior
        ),
        forbidden_mw,
        AuthMiddleware(vips=vips),
    ]

    # Apply to business messages (VIP path) and private messages/callbacks.
    for mw in middlewares:
        dp.message.middleware(mw)
        dp.business_message.middleware(mw)
        dp.callback_query.middleware(mw)

    root = Router(name="root")
    root.include_router(build_callback_router(admin=admin, correct_sessions=sessions))
    root.include_router(
        build_admin_router(
            owner_telegram_id=owner_telegram_id,
            vips=vips,
            admin=admin,
            correct_sessions=sessions,
        )
    )
    root.include_router(build_business_router(orchestrator=orchestrator))
    dp.include_router(root)

    return TelegramWiring(
        dispatcher=dp,
        middleware_order=F1_MIDDLEWARE_ORDER,
        correct_sessions=sessions,
        forbidden_middleware=forbidden_mw,
        registered_middlewares=list(middlewares),
    )


def registered_middleware_names() -> tuple[str, ...]:
    """F1 ordered middleware names (Freeze absent)."""
    return F1_MIDDLEWARE_ORDER


__all__ = [
    "TelegramWiring",
    "build_dispatcher",
    "extract_observer_middleware_names",
    "middleware_class_names",
    "registered_middleware_names",
]
