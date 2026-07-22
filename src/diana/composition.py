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
from diana.application.recovery_startup import (
    DEFAULT_STALE_AFTER,
    run_startup_recovery,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.ports import DelayPolicy
from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import CognitiveDirector
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.planner import Planner
from diana.cognitive.registry import build_default_registry
from diana.config import Settings
from diana.infrastructure.db.repositories.approvals import SqlPendingApprovalStore
from diana.infrastructure.db.repositories.deliveries import SqlPendingDeliveryStore
from diana.infrastructure.db.repositories.escalations import SqlEscalationStore
from diana.infrastructure.db.repositories.history import SqlMessageHistoryRepo
from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore
from diana.infrastructure.db.repositories.traces import SqlTraceStore
from diana.infrastructure.db.repositories.turns import SqlTurnStore
from diana.infrastructure.db.repositories.vips import SqlVipStore
from diana.infrastructure.db.session import create_engine, create_session_factory
from diana.learning.post_turn import LearningService
from diana.llm.deepseek import DeepSeekProvider
from diana.llm.fake import FakeLLM
from diana.telegram.actuator import AiogramTelegramActuator
from diana.telegram.handlers.callbacks import CorrectSessionStore
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
    """Production-ish random delays (4–14s initial; typing ~text length)."""

    def __init__(
        self,
        *,
        initial_min: float = 4.0,
        initial_max: float = 14.0,
        typing_per_char: float = 0.03,
        typing_max: float = 5.0,
        rng: random.Random | None = None,
    ) -> None:
        self._min = initial_min
        self._max = initial_max
        self._per_char = typing_per_char
        self._typing_max = typing_max
        self._rng = rng or random.Random()

    def initial_delay_seconds(self) -> float:
        return self._rng.uniform(self._min, self._max)

    def typing_duration_seconds(self, text: str) -> float:
        return min(len(text or "") * self._per_char, self._typing_max)


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
    traces = SqlTraceStore(sf)
    vips = SqlVipStore(sf)
    config_store = SqlSystemConfigStore(sf)

    token = settings.telegram_bot_token.get_secret_value()
    bot_inst = bot or Bot(token=token)
    actuator = AiogramTelegramActuator(bot_inst)
    notifier = AiogramOwnerNotifier(
        bot_inst, owner_telegram_id=settings.owner_telegram_id
    )
    clock = SystemClock()
    policy = delay_policy or RandomDelayPolicy()
    behavior = BehaviorEngine(
        actuator, deliveries, clock=clock, delay_policy=policy
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

    registry = build_default_registry(history)
    director = CognitiveDirector(
        analyst=Analyst(provider),
        planner=Planner(),
        registry=registry,
        context_builder=ContextBuilder(),
        generator=Generator(provider),
        evaluator=Evaluator(provider),
        decider=Decider(),
        trace=traces,
        persona=DEFAULT_PERSONA,
        status_sink=coordinator.transition_sink,
    )
    learning = LearningService(traces)
    orchestrator = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learning,
        history=history,
    )

    # Forbidden keywords loaded at boot (async load deferred to startup helper).
    forbidden_keywords: list[str] = []
    sessions = CorrectSessionStore()
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
    "build_app",
    "load_forbidden_keywords",
    "run_app_startup_recovery",
]
