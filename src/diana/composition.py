"""Composition root — wire Settings → stores → Director → Telegram.

May import all layers. Cognitive/application/behavior purity is unchanged.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from diana.application.admin_service import AdminService
from diana.application.admin_trace_service import AdminTraceService
from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.gray_zone_service import GrayZoneService
from diana.application.recovery_startup import (
    DEFAULT_STALE_AFTER,
    run_startup_recovery,
)
from diana.application.sandbox import SandboxService
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.application.ports import TurnStore
from diana.behavior.engine import BehaviorEngine
from diana.behavior.ports import DelayPolicy
from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import ANALYST_HISTORY_LIMIT, CognitiveDirector
from diana.cognitive.embedding import EmbeddingService
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.planner import Planner
from diana.cognitive.policy_distiller import PolicyDistiller
from diana.cognitive.registry import build_default_registry
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS
from diana.config import Settings
from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo
from diana.infrastructure.db.repositories.staging import StagingCandidateRepo
from diana.infrastructure.db.repositories.approvals import SqlPendingApprovalStore
from diana.infrastructure.db.repositories.deliveries import SqlPendingDeliveryStore
from diana.infrastructure.db.repositories.escalations import SqlEscalationStore
from diana.infrastructure.db.repositories.history import SqlMessageHistoryRepo
from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore
from diana.infrastructure.db.repositories.traces import SqlTraceStore
from diana.infrastructure.db.repositories.turns import SqlTurnStore
from diana.infrastructure.db.repositories.vips import SqlVipStore
from diana.infrastructure.db.session import create_engine, create_session_factory
from diana.infrastructure.db.repositories.examples import ExamplesRepo
from diana.infrastructure.db.repositories.memories import MemoriesRepo
from diana.infrastructure.db.repositories.policies import PoliciesRepo
from diana.learning.post_turn import LearningService
from diana.llm.deepseek import DeepSeekProvider
from diana.llm.fake import FakeLLM
from diana.telegram.actuator import AiogramTelegramActuator
from diana.telegram.handlers.callbacks import CorrectSessionStore
from diana.telegram.handlers.doctrine import build_doctrine_router
from diana.telegram.notifier import AiogramOwnerNotifier
from diana.telegram.setup import TelegramWiring, build_dispatcher

logger = logging.getLogger("diana.composition")

DEFAULT_PERSONA = (
    "You are Diana, a warm and professional VIP chat assistant. "
    "Write natural, concise replies in the owner's voice."
)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        import asyncio

        await asyncio.sleep(seconds)


class RandomDelayPolicy(DelayPolicy):
    """Production-ish random delays (4–14s initial; typing ~text length).

    REQ-NFR-01: initial_min must be > 0 (FixedDelayPolicy remains free for tests).
    """

    def __init__(
        self,
        *,
        initial_min: float = 4.0,
        initial_max: float = 14.0,
        typing_per_char: float = 0.03,
        typing_max: float = 5.0,
        rng: random.Random | None = None,
    ) -> None:
        if initial_min <= 0:
            raise ValueError("initial_min must be > 0 (REQ-NFR-01)")
        if initial_max < initial_min:
            raise ValueError("initial_max must be >= initial_min")
        self._min = initial_min
        self._max = initial_max
        self._per_char = typing_per_char
        self._typing_max = typing_max
        self._rng = rng or random.Random()

    def initial_delay_seconds(self) -> float:
        return self._rng.uniform(self._min, self._max)

    def typing_duration_seconds(self, text: str) -> float:
        return min(len(text or "") * self._per_char, self._typing_max)


class TurnStoreStatusReader:
    """Thin adapter: TurnStore → behavior TurnStatusReader (no cognitive imports)."""

    def __init__(self, turns: TurnStore) -> None:
        self._turns = turns

    async def get_status(self, turn_id: Any) -> str | None:
        row = await self._turns.get(turn_id)
        return None if row is None else row.status


@dataclass
class AppContainer:
    """Fully wired F1 application graph."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    bot: Bot
    dispatcher: Dispatcher
    orchestrator: TurnOrchestrator
    admin: AdminService
    behavior: BehaviorEngine
    coordinator: TurnCoordinator
    vips: SqlVipStore
    deliveries: SqlPendingDeliveryStore
    approvals: SqlPendingApprovalStore
    notifier: AiogramOwnerNotifier
    correct_sessions: CorrectSessionStore
    forbidden_keywords: list[str]
    clock: SystemClock
    wiring: TelegramWiring
    gray_zone: GrayZoneService | None = None
    sandbox: SandboxService | None = None
    admin_trace: AdminTraceService | None = None
    trace_store: SqlTraceStore | None = None


def build_app(
    settings: Settings,
    *,
    bot: Bot | None = None,
    llm: Any | None = None,
    use_fake_llm: bool = False,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    engine: AsyncEngine | None = None,
    delay_policy: DelayPolicy | None = None,
) -> AppContainer:
    """Wire SQL repos → Director → Orchestrator → Admin → Dispatcher."""
    eng = engine or create_engine(settings.database_url.get_secret_value())
    sf = session_factory or create_session_factory(eng)

    turns = SqlTurnStore(sf)
    approvals = SqlPendingApprovalStore(sf)
    deliveries = SqlPendingDeliveryStore(sf)
    escalations = SqlEscalationStore(sf)
    history = SqlMessageHistoryRepo(sf)
    traces = SqlTraceStore(sf, ttl_days=settings.trace_ttl_days)
    admin_trace = AdminTraceService(traces=traces, trace_ttl_days=settings.trace_ttl_days)
    vips = SqlVipStore(sf)
    config_store = SqlSystemConfigStore(sf)

    token = settings.telegram_bot_token.get_secret_value()
    bot_inst = bot or Bot(token=token)
    actuator = AiogramTelegramActuator(bot_inst)
    notifier = AiogramOwnerNotifier(
        bot_inst, owner_telegram_id=settings.owner_telegram_id
    )
    clock = SystemClock()
    policy = delay_policy or RandomDelayPolicy(
        initial_min=settings.delivery_initial_delay_min,
        initial_max=settings.delivery_initial_delay_max,
    )
    feature_advanced_behavior = settings.feature_advanced_behavior
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=clock,
        delay_policy=policy,
        turn_status=TurnStoreStatusReader(turns),
        max_send_attempts=settings.delivery_max_send_attempts,
        retry_backoff_seconds=settings.delivery_retry_backoff_seconds,
        feature_advanced_behavior=feature_advanced_behavior,
        quirk_probability=0.05 if feature_advanced_behavior else 0.0,
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
        owner_telegram_id=settings.owner_telegram_id,
        delivery_mode=settings.global_mode,
        feature_advanced_behavior=feature_advanced_behavior,
        vip_store=vips,
    )

    if llm is not None:
        provider = llm
    elif use_fake_llm or not settings.deepseek_api_key.get_secret_value().strip():
        provider = FakeLLM()
        logger.warning("using FakeLLM — set DEEPSEEK_API_KEY for production")
    else:
        provider = DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            base_url=settings.llm_base_url,
        )

    # F2 knowledge services (Item 1)
    embedding_svc = EmbeddingService()  # lazy, no model load at boot
    memories_repo = MemoriesRepo(sf)
    policies_repo = PoliciesRepo(sf)
    examples_repo = ExamplesRepo(sf)

    # ---- F2 Item 3: feature flags, gray zone, sandbox ----
    # Feature flags come from Settings (source of truth). DB-side overrides
    # are not implemented in F2 (load_feature_flags removed per review).
    feature_gray_zone_enabled = settings.feature_gray_zone_enabled
    feature_sandbox_enabled = settings.feature_sandbox_enabled
    feature_autonomous_mode = settings.feature_autonomous_mode

    # GrayZoneService — created only when the feature is enabled.
    # When disabled, TurnOrchestrator receives None (dead-code guard).
    if feature_gray_zone_enabled:
        staging_repo = StagingCandidateRepo(sf)
        gray_zone_repo = GrayZoneQueryRepo(sf)
        policy_distiller = PolicyDistiller()
        gray_zone = GrayZoneService(
            query_repo=gray_zone_repo,
            vip_store=vips,
            staging_repo=staging_repo,
            distiller=policy_distiller,
        )
    else:
        gray_zone = None

    # SandboxService — minimal F2 sandbox (profiles + trace isolation)
    sandbox = SandboxService() if feature_sandbox_enabled else None

    # Decider with gray zone + autonomous flags (must be before Director).
    # Defaults false → F2 parity; L3 send only when flag true and dims meet mins.
    decider = Decider(
        feature_gray_zone_enabled=feature_gray_zone_enabled,
        feature_autonomous_mode=feature_autonomous_mode,
        autonomous_thresholds=dict(DEFAULT_AUTONOMOUS_THRESHOLDS),
    )

    # AMS L2 gate — always constructed; with L1 false is_autonomous_enabled → False.
    ams = AutonomousModeService(
        feature_autonomous_mode=feature_autonomous_mode,
        global_mode=settings.global_mode,
        vip_store=vips,
        notifier=notifier,
        autonomous_thresholds=dict(DEFAULT_AUTONOMOUS_THRESHOLDS),
    )

    registry = build_default_registry(
        history,
        memory_repo=memories_repo,
        policy_repo=policies_repo,
        examples_repo=examples_repo,
        embedding_service=embedding_svc,
    )
    director = CognitiveDirector(
        analyst=Analyst(provider),
        planner=Planner(),
        registry=registry,
        context_builder=ContextBuilder(),
        generator=Generator(provider),
        evaluator=Evaluator(provider),
        decider=decider,
        trace=traces,
        persona=DEFAULT_PERSONA,
        # Same history port as registry — Analyst window is chat-scoped only (R1).
        history=history,
        analyst_history_limit=ANALYST_HISTORY_LIMIT,
        # TurnStatusSink protocol: object with .transition(...).
        # Must inject the coordinator itself, not the unbound method.
        status_sink=coordinator,
    )
    learning = LearningService(traces)
    orchestrator = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learning,
        history=history,
        gray_zone=gray_zone,
        feature_gray_zone_enabled=feature_gray_zone_enabled,
        behavior=behavior,
        autonomous_mode=ams,
        vip_store=vips,
        traces=traces,
        delivery_mode=settings.global_mode,
        feature_advanced_behavior=feature_advanced_behavior,
    )

    # Forbidden keywords loaded at boot (async load deferred to startup helper).
    forbidden_keywords: list[str] = []
    sessions = CorrectSessionStore()

    # Doctrine router — only wired when gray zone feature is enabled.
    doctrine_router = (
        build_doctrine_router(gray_zone=gray_zone, coordinator=coordinator)
        if gray_zone is not None
        else None
    )

    wiring = build_dispatcher(
        orchestrator=orchestrator,
        admin=admin,
        coordinator=coordinator,
        escalations=escalations,
        notifier=notifier,
        behavior=behavior,
        vips=vips,
        owner_telegram_id=settings.owner_telegram_id,
        forbidden_keywords=forbidden_keywords,
        correct_sessions=sessions,
        doctrine_router=doctrine_router,
        admin_trace=admin_trace,
    )

    return AppContainer(
        settings=settings,
        engine=eng,
        session_factory=sf,
        bot=bot_inst,
        dispatcher=wiring.dispatcher,
        orchestrator=orchestrator,
        admin=admin,
        behavior=behavior,
        coordinator=coordinator,
        vips=vips,
        deliveries=deliveries,
        approvals=approvals,
        notifier=notifier,
        correct_sessions=sessions,
        forbidden_keywords=forbidden_keywords,
        clock=clock,
        wiring=wiring,
        gray_zone=gray_zone,
        sandbox=sandbox,
        admin_trace=admin_trace,
        trace_store=traces,
    )


async def load_forbidden_keywords(app: AppContainer) -> list[str]:
    """Load keywords from system_config into the container (boot-time)."""
    store = SqlSystemConfigStore(app.session_factory)
    kws = await store.get_forbidden_keywords()
    app.forbidden_keywords.clear()
    app.forbidden_keywords.extend(kws)
    # Explicit setter — no Dispatcher graph walk.
    app.wiring.forbidden_middleware.set_keywords(kws)
    logger.info("forbidden_keywords_loaded", extra={"count": len(kws)})
    return kws


async def run_app_startup_recovery(app: AppContainer) -> Any:
    """Expire mid-flight deliveries; re-notify waiting approvals."""
    return await run_startup_recovery(
        deliveries=app.deliveries,
        approvals=app.approvals,
        notifier=app.notifier,
        clock=app.clock,
        stale_after=DEFAULT_STALE_AFTER,
    )


__all__ = [
    "AppContainer",
    "DEFAULT_PERSONA",
    "RandomDelayPolicy",
    "SystemClock",
    "TurnStoreStatusReader",
    "build_app",
    "load_forbidden_keywords",
    "run_app_startup_recovery",
]
