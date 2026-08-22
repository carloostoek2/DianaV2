"""Dispatcher registration — F1 middleware order + routers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiogram import Dispatcher, Router

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_shadow_service import AdminShadowService
from diana.application.ephemeral_event_service import EphemeralEventService
from diana.application.link import LinkCoordinator
from diana.application.memory_approval_service import MemoryApprovalService
from diana.application.profile_admin_service import ProfileAdminService
from diana.application.admin_service import AdminService
from diana.application.admin_trace_service import AdminTraceService
from diana.application.ports import (
    AtencionCycleStore,
    BehaviorCanceller,
    BusinessConnectionStore,
    EscalationStore,
    GrayZoneServicePort,
    OwnerNotifierPort,
    TrainingModeStore,
    VipStore,
)
from diana.application.persona_admin_service import PersonaAdminService
from diana.application.promo_service import PromoService
from diana.application.staging_service import StagingService
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.telegram.handlers.admin import build_admin_router
from diana.telegram.handlers.business import build_business_router
from diana.telegram.handlers.business_connection import build_business_connection_router
from diana.telegram.handlers.menu import MenuSessionStore, build_menu_router
from diana.telegram.handlers.callbacks import (
    CorrectSessionStore,
    build_callback_router,
)
from diana.telegram.handlers.doctrine import (
    DoctrineSessionStore,
    build_doctrine_router,
)
from diana.telegram.handlers.link import build_link_callback_router
from diana.telegram.handlers.staging import build_staging_router
from diana.telegram.handlers.memory_approval import build_memory_approval_router
from diana.telegram.freeze_middleware import FreezeCheckMiddleware
from diana.telegram.middlewares import F2_MIDDLEWARE_ORDER
from diana.telegram.middlewares.auth import AuthMiddleware
from diana.telegram.middlewares.business_connection import BusinessConnectionMiddleware
from diana.telegram.middlewares.dedup import DedupMiddleware
from diana.telegram.middlewares.error_handler import ErrorHandlerMiddleware
from diana.telegram.middlewares.forbidden import ForbiddenKeywordsMiddleware
from diana.telegram.middlewares.link import LinkCoordinatorMiddleware
from diana.telegram.middlewares.logging import LoggingMiddleware
from diana.telegram.middlewares.owner import OwnerDetectionMiddleware
from diana.telegram.middlewares.rate_limit import RateLimitMiddleware


@dataclass
class TelegramWiring:
    """Built dispatcher + ordered middleware class names for tests."""

    dispatcher: Dispatcher
    middleware_order: tuple[str, ...]
    correct_sessions: CorrectSessionStore
    forbidden_middleware: ForbiddenKeywordsMiddleware
    registered_middlewares: list[Any]
    menu_sessions: MenuSessionStore


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
    doctrine_router: Router | None = None,
    doctrine_sessions: DoctrineSessionStore | None = None,
    gray_zone: GrayZoneServicePort | None = None,
    staging: StagingService | None = None,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    shadow_admin: AdminShadowService | None = None,
    llm_config_store: Any | None = None,
    llm_default_model: str = "",
    llm_default_base_url: str = "",
    profile_admin: ProfileAdminService | None = None,
    persona_admin: PersonaAdminService | None = None,
    feature_persona_admin_enabled: bool = False,
    promo: PromoService | None = None,
    feature_promo_enabled: bool = False,
    feature_general_mode_enabled: bool = False,
    sandbox: object | None = None,
    training_mode: TrainingModeStore | None = None,
    config_store: TrainingModeStore | None = None,
    atencion_cycles: AtencionCycleStore | None = None,
    rate_limit_max_events: int = 20,
    rate_limit_window_s: float = 10.0,
    history_seed: object | None = None,
    draft_variants: object | None = None,
    dedup_ttl_s: float = 300.0,
    bc_store: BusinessConnectionStore | None = None,
    history: object | None = None,
    backfill_queue: object | None = None,
    memory_approval: MemoryApprovalService | None = None,
    ephemeral_event_service: EphemeralEventService | None = None,
    link: LinkCoordinator | None = None,
    link_chat_id: int | None = None,
    feature_link_enabled: bool = False,
) -> TelegramWiring:
    """Register F1 middleware order and thin routers."""
    dp = Dispatcher()
    sessions = correct_sessions or CorrectSessionStore()
    menu_sessions = MenuSessionStore()

    # first registered = outermost (aiogram wraps with reversed()).
    # Order: ErrorHandler → Dedup → RateLimit → Logging → BC → Link → Owner → Freeze → Auth → Forbidden.
    # Auth before Forbidden: VIP allowlist gates J.4/forbidden escalate.
    forbidden_mw = ForbiddenKeywordsMiddleware(
        keywords=forbidden_keywords,
        coordinator=coordinator,
        escalations=escalations,
        notifier=notifier,
        vips=vips,
        behavior=behavior,  # type: ignore[arg-type]  # engine implements deliver
        feature_general_mode_enabled=feature_general_mode_enabled,
    )
    middlewares: list[Any] = [
        ErrorHandlerMiddleware(),
        DedupMiddleware(ttl_s=dedup_ttl_s),
        RateLimitMiddleware(
            max_events=rate_limit_max_events,
            window_s=rate_limit_window_s,
            owner_telegram_id=owner_telegram_id,
        ),
        LoggingMiddleware(),
        BusinessConnectionMiddleware(),
        LinkCoordinatorMiddleware(
            link=link,
            link_chat_id=link_chat_id,
            enabled=feature_link_enabled,
        ),
        OwnerDetectionMiddleware(
            owner_telegram_id=owner_telegram_id, coordinator=coordinator, history=history
        ),
        FreezeCheckMiddleware(
            vips=vips,
            gray_zone=gray_zone,
            notifier=notifier,
            general_mode_enabled=feature_general_mode_enabled,
        ),
        AuthMiddleware(
            vips=vips,
            promo=promo,
            feature_promo_enabled=feature_promo_enabled,
            feature_general_mode_enabled=feature_general_mode_enabled,
            sandbox=sandbox,
            training_mode=training_mode,
            atencion_cycles=atencion_cycles,
        ),
        forbidden_mw,
    ]

    # Apply to business messages (VIP path), edited business messages,
    # and private messages/callbacks.
    for mw in middlewares:
        dp.message.middleware(mw)
        dp.business_message.middleware(mw)
        dp.edited_business_message.middleware(mw)
        # FreezeCheckMiddleware is a no-op for non-Message events so skip it on
        # callback_query to keep the middleware chain lean (LOW-3).
        if not isinstance(mw, FreezeCheckMiddleware):
            dp.callback_query.middleware(mw)

    # Minimal middleware for BusinessConnection lifecycle (system event, not user message).
    # Only ErrorHandler (outermost) + Logging. No Auth, FreezeCheck, RateLimit, Dedup.
    for bc_mw in [ErrorHandlerMiddleware(), LoggingMiddleware()]:
        dp.business_connection.middleware(bc_mw)

    root = Router(name="root")
    # Doctrine router must be included BEFORE the catch-all callback router
    # so that doctrine-specific prefixes (dr:, dx:, de:) are handled first.
    if doctrine_router is not None:
        root.include_router(doctrine_router)
    # Staging router (sp:/sd: + /staging) before catch-all callbacks.
    root.include_router(
        build_staging_router(
            staging=staging,
            owner_telegram_id=owner_telegram_id,
        )
    )
    # Memory approval router (mp:/md: + /memoria) — AFTER staging, BEFORE
    # the menu and the catch-all so mp:/md: are never swallowed (A1). The
    # router is inert when memory_approval is None (flag OFF).
    root.include_router(
        build_memory_approval_router(
            memory=memory_approval,
            owner_telegram_id=owner_telegram_id,
        )
    )
    root.include_router(
        build_menu_router(
            owner_telegram_id=owner_telegram_id,
            vips=vips,
            admin_trace=admin_trace,
            admin_metrics=admin_metrics,
            shadow_admin=shadow_admin,
            llm_config_store=llm_config_store,
            llm_default_model=llm_default_model,
            llm_default_base_url=llm_default_base_url,
            sandbox=sandbox,  # type: ignore[arg-type]
            staging=staging,
            coordinator=coordinator,
            profile_admin=profile_admin,
            persona_admin=persona_admin,
            feature_persona_admin_enabled=feature_persona_admin_enabled,
            menu_sessions=menu_sessions,
            config_store=config_store,
            history_seed=history_seed,
            backfill_queue=backfill_queue,
            ephemeral_event_service=ephemeral_event_service,
        )
    )
    if link is not None:
        root.include_router(
            build_link_callback_router(
                link=link,
                owner_telegram_id=owner_telegram_id,
            )
        )
    root.include_router(
        build_callback_router(
            admin=admin,
            correct_sessions=sessions,
            admin_trace=admin_trace,
            admin_metrics=admin_metrics,
            owner_telegram_id=owner_telegram_id,
            menu_sessions=menu_sessions,
            profile_admin=profile_admin,
            draft_variants=draft_variants,
        )
    )
    root.include_router(
        build_admin_router(
            owner_telegram_id=owner_telegram_id,
            vips=vips,
            admin=admin,
            correct_sessions=sessions,
            admin_trace=admin_trace,
            admin_metrics=admin_metrics,
            profile_admin=profile_admin,
            sandbox=sandbox,  # type: ignore[arg-type]
            coordinator=coordinator,
            history_seed=history_seed,
            backfill_queue=backfill_queue,
            doctrine_sessions=doctrine_sessions,
            gray_zone=gray_zone,
        )
    )
    root.include_router(
        build_business_router(
            orchestrator=orchestrator,
            on_vip_inbound=sessions.cancel_combo_for_chat,
        )
    )
    if bc_store is not None:
        root.include_router(build_business_connection_router(store=bc_store))
    dp.include_router(root)

    return TelegramWiring(
        dispatcher=dp,
        middleware_order=F2_MIDDLEWARE_ORDER,
        correct_sessions=sessions,
        forbidden_middleware=forbidden_mw,
        registered_middlewares=list(middlewares),
        menu_sessions=menu_sessions,
    )


def registered_middleware_names() -> tuple[str, ...]:
    """Ordered middleware names (ErrorHandler@0, Dedup@1, RateLimit@2, FreezeCheck@6)."""
    return F2_MIDDLEWARE_ORDER


__all__ = [
    "TelegramWiring",
    "build_dispatcher",
    "extract_observer_middleware_names",
    "middleware_class_names",
    "registered_middleware_names",
]
