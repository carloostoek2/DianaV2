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

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_service import AdminService
from diana.application.admin_trace_service import AdminTraceService
from diana.application.profile_admin_service import ProfileAdminService
from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.calibration_service import CalibrationService
from diana.application.gray_zone_service import GrayZoneService
from diana.application.metrics_service import MetricsAggregationService
from diana.application.promo_service import PromoService
from diana.application.recontact_service import (
    ApprovalsDeliveriesRouteResolver,
    RecontactService,
)
from diana.cognitive.runtime_thresholds import RuntimeThresholds
from diana.infrastructure.db.repositories.owner_marks import SqlOwnerMarkStore
from diana.application.recovery_startup import (
    DEFAULT_STALE_AFTER,
    run_startup_recovery,
)
from diana.application.sandbox import SandboxService
from diana.application.sandbox_knowledge import SandboxKnowledgeAugmenter
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.application.ports import TurnStore
from diana.behavior.engine import BehaviorEngine
from diana.behavior.ports import DelayPolicy
from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import ANALYST_HISTORY_LIMIT, CognitiveDirector
from diana.cognitive.repetition_guard import RepetitionGuard
from diana.cognitive.template_gate import TemplateGate, TemplateRule
from diana.cognitive.embedding import EmbeddingService
from diana.application.j4_triggers import IA_TEMPLATE

from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.planner import Planner
from diana.cognitive.policy_distiller import PolicyDistiller
from diana.cognitive.persona_catalog import get_persona_catalog
from diana.cognitive.registry import build_default_registry
from diana.cognitive.thresholds import (
    DEFAULT_AUTONOMOUS_THRESHOLDS,
    DEFAULT_SUPERVISED_THRESHOLDS,
)
from diana.config import Settings
from diana.infrastructure.db.repositories.calibration_data import (
    SqlCalibrationDataSource,
)
from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo
from diana.infrastructure.db.repositories.learning_metrics import (
    SqlLearningMetricsRepo,
)
from diana.infrastructure.db.repositories.metrics_data import SqlMetricsDataSource
from diana.infrastructure.db.repositories.staging import StagingCandidateRepo
from diana.infrastructure.db.repositories.approvals import SqlPendingApprovalStore
from diana.infrastructure.db.repositories.deliveries import SqlPendingDeliveryStore
from diana.infrastructure.db.repositories.escalations import SqlEscalationStore
from diana.infrastructure.db.repositories.history import SqlMessageHistoryRepo
from diana.infrastructure.db.repositories.promo_executions import PromoExecutionRepo
from diana.infrastructure.db.repositories.promo_triggers import PromoTriggerRepo
from diana.infrastructure.db.repositories.recontact_schedules import (
    RecontactScheduleRepo,
)
from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore
from diana.infrastructure.db.repositories.traces import SqlTraceStore
from diana.infrastructure.db.repositories.turns import SqlTurnStore
from diana.infrastructure.db.repositories.vips import SqlVipStore
from diana.infrastructure.db.session import create_engine, create_session_factory
from diana.infrastructure.db.repositories.examples import ExamplesRepo
from diana.infrastructure.db.repositories.memories import MemoriesRepo
from diana.infrastructure.db.repositories.policies import PoliciesRepo
from diana.infrastructure.db.repositories.profiles import ProfilesRepo
from diana.learning.post_turn import LearningService
from diana.llm.deepseek import DeepSeekProvider
from diana.llm.fake import FakeLLM
from diana.telegram.actuator import AiogramTelegramActuator
from diana.telegram.handlers.callbacks import CorrectSessionStore
from diana.telegram.handlers.doctrine import build_doctrine_router
from diana.telegram.notifier import AiogramOwnerNotifier
from diana.telegram.setup import TelegramWiring, build_dispatcher

logger = logging.getLogger("diana.composition")

# Production persona from Anexo J.1 static catalog (lazy — no import-time I/O).
def _default_persona() -> str:
    return str(get_persona_catalog()["voz_configurada"]["persona"])


def __getattr__(name: str):
    """Lazy DEFAULT_PERSONA export without module-level catalog load."""
    if name == "DEFAULT_PERSONA":
        return _default_persona()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    recontact: RecontactService | None = None
    promo: PromoService | None = None
    calibration: CalibrationService | None = None
    metrics: MetricsAggregationService | None = None
    admin_metrics: AdminMetricsService | None = None
    profile_admin: ProfileAdminService | None = None
    runtime_thresholds: RuntimeThresholds | None = None


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
    profiles_repo = ProfilesRepo(sf)

    # ---- F2 Item 3: feature flags, gray zone, sandbox ----
    # Feature flags come from Settings (source of truth). DB-side overrides
    # are not implemented in F2 (load_feature_flags removed per review).
    feature_gray_zone_enabled = settings.feature_gray_zone_enabled
    feature_sandbox_enabled = settings.feature_sandbox_enabled
    feature_autonomous_mode = settings.feature_autonomous_mode

    # GrayZoneService — created only when the feature is enabled.
    # When disabled, TurnOrchestrator receives None (dead-code guard).
    gray_zone_repo: GrayZoneQueryRepo | None = None
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

    # SandboxService — v1 session model + package fixture catalog (not insert_sandbox)
    sandbox = SandboxService() if feature_sandbox_enabled else None
    knowledge_augmenter = (
        SandboxKnowledgeAugmenter(sandbox) if sandbox is not None else None
    )

    # Shared runtime thresholds: calibration updates mins live for Decider (R2).
    runtime_thresholds = RuntimeThresholds(
        autonomous=dict(DEFAULT_AUTONOMOUS_THRESHOLDS),
    )

    # Decider with gray zone + autonomous flags (must be before Director).
    # Defaults false → F2 parity; L3 send only when flag true and dims meet mins.
    decider = Decider(
        feature_gray_zone_enabled=feature_gray_zone_enabled,
        feature_autonomous_mode=feature_autonomous_mode,
        runtime_thresholds=runtime_thresholds,
    )

    # AMS L2 gate — always constructed; with L1 false is_autonomous_enabled → False.
    ams = AutonomousModeService(
        feature_autonomous_mode=feature_autonomous_mode,
        global_mode=settings.global_mode,
        vip_store=vips,
        notifier=notifier,
        autonomous_thresholds=dict(DEFAULT_AUTONOMOUS_THRESHOLDS),
    )

    # F3 recontact — always construct; methods no-op when flag false.
    # Built before TurnCoordinator so BR-07 cancel hook can be injected.
    feature_recontact_enabled = settings.feature_recontact_enabled
    recontact_schedules_repo = RecontactScheduleRepo(sf)
    route_resolver = ApprovalsDeliveriesRouteResolver(approvals, deliveries)

    async def _has_open_gray_zone(vip_id: Any) -> bool:
        if gray_zone_repo is None:
            return False
        open_rows = await gray_zone_repo.list_open()
        return any(q.vip_id == vip_id for q in open_rows)

    async def _is_sandbox_vip(vip_id: Any) -> bool:
        """True when VIP's private chat_id has an active sandbox session.

        Sandbox sessions are keyed by Telegram chat_id; for private VIP
        chats that equals ``telegram_user_id``.
        """
        if sandbox is None:
            return False
        vip = await vips.get_by_id(vip_id)
        if vip is None:
            return False
        return sandbox.is_active(vip.telegram_user_id)

    recontact = RecontactService(
        feature_recontact_enabled=feature_recontact_enabled,
        schedules=recontact_schedules_repo,
        vips=vips,
        config=config_store,
        approvals=approvals,
        ams=ams,
        behavior=behavior,
        turns=turns,
        route_resolver=route_resolver,
        notifier=notifier,
        clock=clock,
        delivery_mode=settings.global_mode,
        has_open_gray_zone=(
            _has_open_gray_zone if feature_gray_zone_enabled else None
        ),
        is_sandbox_vip=_is_sandbox_vip if sandbox is not None else None,
    )

    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,
        recontact=recontact,
        feature_recontact_enabled=feature_recontact_enabled,
    )
    owner_marks = SqlOwnerMarkStore(sf)
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
        fp_marks=owner_marks,
        sandbox=sandbox,
    )

    catalog = get_persona_catalog()
    voz = catalog["voz_configurada"]
    registry = build_default_registry(
        history,
        memory_repo=memories_repo,
        policy_repo=policies_repo,
        examples_repo=examples_repo,
        profile_repo=profiles_repo,
        embedding_service=embedding_svc,
        persona_facts=catalog["persona_facts"],
        voice_patterns=catalog["voice_patterns"],
        static_policies=catalog["policies"],
    )
    # H6: pure TemplateGate pre-pipeline (deteccion_ia before saludo_constante).
    deteccion_ia = TemplateRule(
        id="deteccion_ia",
        trigger_patterns=[
            "eres una ia",
            "eres un bot",
            "eres ia",
            "hablo con una ia",
            "hablo con un bot",
            "eres real",
        ],
        max_words=None,
        response_pool=[IA_TEMPLATE],
        reason="plantilla_deteccion_ia",
    )
    saludo_constante = TemplateRule(
        id="saludo_constante",
        trigger_patterns=[
            "hola",
            "holaa",
            "holis",
            "buenas",
            "buenos días",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "hey",
            "qué tal",
            "que tal",
        ],

        max_words=4,
        response_pool=["Holis 😁", "Holaa, qué tal?", "Hola amor, cómo vas?"],
        reason="plantilla_saludo",
    )
    template_gate = TemplateGate(rules=[deteccion_ia, saludo_constante])
    director = CognitiveDirector(
        analyst=Analyst(provider),
        planner=Planner(),
        registry=registry,
        context_builder=ContextBuilder(),
        generator=Generator(provider),
        evaluator=Evaluator(provider),
        decider=decider,
        trace=traces,
        persona=str(voz["persona"]),
        style_rules=list(voz["reglas_estilo"]),
        # Same history port as registry — Analyst window is chat-scoped only (R1).
        history=history,
        analyst_history_limit=ANALYST_HISTORY_LIMIT,
        # TurnStatusSink protocol: object with .transition(...).
        # Must inject the coordinator itself, not the unbound method.
        status_sink=coordinator,
        # H4: prior intents + pure guard for pregunta_repetida early-exit.
        recent_intents=traces,
        repetition_guard=RepetitionGuard(threshold=3),
        template_gate=template_gate,
        # Supervised naturalness redraft min (Director pre-Decider; not send gate).
        naturalness_min=float(DEFAULT_SUPERVISED_THRESHOLDS["naturalness_min"]),
        knowledge_augmenter=knowledge_augmenter,
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
        sandbox=sandbox,
    )

    # Forbidden keywords loaded at boot (async load deferred to startup helper).
    forbidden_keywords: list[str] = []
    sessions = CorrectSessionStore()

    # Doctrine router — only wired when gray zone feature is enabled.
    doctrine_router = (
        build_doctrine_router(
            gray_zone=gray_zone,
            coordinator=coordinator,
            owner_telegram_id=settings.owner_telegram_id,
        )
        if gray_zone is not None
        else None
    )

    # F3 promo (non-VIP) — always construct; feature flag gates execute/match path.
    feature_promo_enabled = settings.feature_promo_enabled
    promo = PromoService(
        feature_promo_enabled=feature_promo_enabled,
        triggers=PromoTriggerRepo(sf),
        executions=PromoExecutionRepo(sf),
        config=config_store,
        behavior=behavior,
        turns=turns,
        clock=clock,
        delivery_mode=settings.global_mode,
    )

    # F3 Pool 3 — calibration / metrics / admin dashboard (glue only).
    # calibrate_thresholds is flag-gated inside CalibrationService; detect_drift
    # remains readable so MetricsAggregationService can score style_drift.
    feature_calibration_enabled = settings.feature_calibration_enabled
    cal_data = SqlCalibrationDataSource(sf)
    learning_metrics = SqlLearningMetricsRepo(sf)
    metrics_data = SqlMetricsDataSource(sf)
    calibration = CalibrationService(
        feature_calibration_enabled=feature_calibration_enabled,
        traces=cal_data,
        config=config_store,
        embeddings=embedding_svc,
        drift_texts=cal_data,
        notifier=notifier if feature_calibration_enabled else None,
        runtime=runtime_thresholds,
    )
    metrics = MetricsAggregationService(
        traces=metrics_data,
        sides=metrics_data,
        store=learning_metrics,
        drift=calibration,
        fp_marks=owner_marks,
    )
    admin_metrics = AdminMetricsService(store=learning_metrics)
    profile_admin = ProfileAdminService(
        profiles=profiles_repo,
        vips=vips,
        owner_telegram_id=settings.owner_telegram_id,
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
        admin_metrics=admin_metrics,
        profile_admin=profile_admin,
        promo=promo,
        feature_promo_enabled=feature_promo_enabled,
        sandbox=sandbox,
        rate_limit_max_events=settings.rate_limit_max_events,
        rate_limit_window_s=settings.rate_limit_window_s,
        dedup_ttl_s=settings.dedup_ttl_s,
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
        recontact=recontact,
        promo=promo,
        calibration=calibration,
        metrics=metrics,
        admin_metrics=admin_metrics,
        profile_admin=profile_admin,
        runtime_thresholds=runtime_thresholds,
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


async def load_runtime_thresholds(app: AppContainer) -> None:
    """Hydrate RuntimeThresholds from system_config at boot (R2 residual).

    Calibration writes DB + live holder; boot must re-read DB so mins survive restart.
    Missing keys leave pure DEFAULT_* / safety from RuntimeThresholds defaults.
    """
    holder = app.runtime_thresholds
    if holder is None:
        return
    store = SqlSystemConfigStore(app.session_factory)
    auto = await store.get_autonomous_thresholds()
    if auto:
        holder.replace_autonomous(auto)
    supervised = await store.get_supervised_thresholds()
    if isinstance(supervised, dict) and "safety_min" in supervised:
        try:
            holder.replace_safety(float(supervised["safety_min"]))
        except (TypeError, ValueError):
            pass
    eval_th = await store.get_eval_thresholds()
    if isinstance(eval_th, dict) and "safety" in eval_th:
        try:
            holder.replace_safety(float(eval_th["safety"]))
        except (TypeError, ValueError):
            pass
    logger.info(
        "runtime_thresholds_loaded",
        extra={
            "autonomous": dict(holder.autonomous),
            "safety": holder.safety,
        },
    )


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
    "load_runtime_thresholds",
    "run_app_startup_recovery",
]
