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

    # Outer middleware order for updates (last registered = outermost in aiogram).
    # We register on business_message / message / callback routers consistently via
    # a root update outer stack using message + business_message + callback_query.
    middlewares: list[Any] = [
        LoggingMiddleware(),
        BusinessConnectionMiddleware(),
        OwnerDetectionMiddleware(
            owner_telegram_id=owner_telegram_id, behavior=behavior
        ),
        ForbiddenKeywordsMiddleware(
            keywords=forbidden_keywords,
            coordinator=coordinator,
            escalations=escalations,
            notifier=notifier,
        ),
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
    )


def registered_middleware_names() -> tuple[str, ...]:
    """F1 ordered middleware names (Freeze absent)."""
    return F1_MIDDLEWARE_ORDER


__all__ = [
    "TelegramWiring",
    "build_dispatcher",
    "registered_middleware_names",
]
