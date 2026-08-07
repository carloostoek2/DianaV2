"""Composition root — wire Settings → stores → Director → Telegram.

May import all layers. Cognitive/application/behavior purity is unchanged.
"""

from __future__ import annotations

import asyncio
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
from diana.application.memory_backfill_queue import MemoryBackfillQueue
from diana.application.mood_engine import MoodEngine
from diana.application.persona_admin_service import PersonaAdminService
from diana.application.persona_catalog_provider import PersonaCatalogProvider
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
from diana.application.staging_service import StagingService
from diana.application.turn_classifier import TurnClassifier
from diana.application.turn_coordinator import TurnCoordinator
from diana.application.turn_orchestrator import TurnOrchestrator
from diana.application.trust_budget_service import TrustBudgetService
from diana.application.emotional_signal_detector import EmotionalSignalDetector
from diana.application.profile_synthesis_service import ProfileSynthesisService
from diana.application.profile_synthesis_trigger_service import (
    ProfileSynthesisTriggerService,
)
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
from diana.infrastructure.db.repositories.business_connections import SqlBusinessConnectionStore
from diana.infrastructure.db.repositories.runtime_timers import SqlRuntimeTimerStore
from diana.infrastructure.db.repositories.recontact_schedules import (
    RecontactScheduleRepo,
)
from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore
from diana.infrastructure.db.repositories.persona_versions import PersonaVersionRepo
from diana.infrastructure.db.repositories.daily_message_limits import (
    SqlDailyMessageLimitStore,
)
from diana.infrastructure.db.repositories.atencion_cycles import SqlAtencionCycleStore
from diana.infrastructure.db.repositories.emotional_signal import (
    SqlEmotionalSignalLogRepo,
)
from diana.infrastructure.db.repositories.turn_category import (
    SqlTurnCategoryLogRepo,
)
from diana.infrastructure.db.repositories.vip_mood_state import SqlVipMoodStateRepo
from diana.infrastructure.db.repositories.vip_profile import SqlVipProfileRepo
from diana.infrastructure.db.repositories.vip_profile_history import (
    SqlVipProfileHistoryRepo,
)
from diana.infrastructure.db.repositories.vip_trust_budget import (
    SqlVipTrustBudgetRepo,
)
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


def _build_vip_history_seed(
    settings: Settings, *, history: Any, notifier: Any = None
) -> Any:
    """Wire Telethon VIP history seed when API credentials + session path are set."""
    from diana.application.vip_history_seed import VipHistorySeedService

    api_id = settings.telethon_api_id
    api_hash = settings.telethon_api_hash.get_secret_value().strip()
    session_path = (settings.telethon_session_path or "").strip()
    fetcher = None
    if api_id and api_hash and session_path:
        from diana.infrastructure.telethon.vip_history_fetcher import (
            TelethonVipHistoryFetcher,
        )

        fetcher = TelethonVipHistoryFetcher(
            api_id=int(api_id),
            api_hash=api_hash,
            session_path=session_path,
        )
        logger.info(
            "vip_history_seed_enabled",
            extra={
                "session_path": session_path,
                "limit": settings.vip_history_seed_limit,
            },
        )
    else:
        logger.info("vip_history_seed_disabled_missing_telethon_config")
    return VipHistorySeedService(
        history=history,
        fetcher=fetcher,
        limit=settings.vip_history_seed_limit,
        notifier=notifier,
    )


class RandomDelayPolicy(DelayPolicy):
    """Mode-aware human-like delays (REQ-HUM-01/04).

    Supervised default: fixed 120s. Autonomous: uniform 180–480s.
    Typing duration scales with text length (8 chars/sec, 2–15s clamped).

    Micro-delays match human typing cadence: pre-read pause, post-read
    reaction time, and inter-message gap (diana v1 parity).

    REQ-NFR-01: all range mins must be > 0 (FixedDelayPolicy free for tests).
    """

    def __init__(
        self,
        *,
        supervised_min: float = 120.0,
        supervised_max: float = 120.0,
        autonomous_min: float = 180.0,
        autonomous_max: float = 480.0,
        typing_per_char: float = 0.125,
        typing_min: float = 2.0,
        typing_max: float = 15.0,
        pre_read_min: float = 0.3,
        pre_read_max: float = 1.0,
        post_read_min: float = 1.5,
        post_read_max: float = 4.0,
        inter_gap_min: float = 1.5,
        inter_gap_max: float = 3.0,
        rng: random.Random | None = None,
    ) -> None:
        for label, lo, hi in (
            ("supervised", supervised_min, supervised_max),
            ("autonomous", autonomous_min, autonomous_max),
        ):
            if lo <= 0:
                raise ValueError(f"{label}_min must be > 0 (REQ-NFR-01)")
            if hi < lo:
                raise ValueError(f"{label}_max must be >= {label}_min")
        self._supervised_min = supervised_min
        self._supervised_max = supervised_max
        self._autonomous_min = autonomous_min
        self._autonomous_max = autonomous_max
        self._per_char = typing_per_char
        self._typing_min = typing_min
        self._typing_max = typing_max
        self._pre_read_min = pre_read_min
        self._pre_read_max = pre_read_max
        self._post_read_min = post_read_min
        self._post_read_max = post_read_max
        self._inter_gap_min = inter_gap_min
        self._inter_gap_max = inter_gap_max
        self._rng = rng or random.Random()

    def initial_delay_seconds(self, mode: str = "supervised") -> float:
        if mode == "autonomous":
            return self._rng.uniform(self._autonomous_min, self._autonomous_max)
        # supervised and fake_delivery share the supervised (owner-visible) wait
        return self._rng.uniform(self._supervised_min, self._supervised_max)

    def typing_duration_seconds(self, text: str) -> float:
        raw = len(text or "") * self._per_char
        return min(max(raw, self._typing_min), self._typing_max)

    def pre_read_delay_seconds(self) -> float:
        return self._rng.uniform(self._pre_read_min, self._pre_read_max)

    def post_read_delay_seconds(self) -> float:
        return self._rng.uniform(self._post_read_min, self._post_read_max)

    def inter_message_gap_seconds(self) -> float:
        return self._rng.uniform(self._inter_gap_min, self._inter_gap_max)


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
    metrics_data: SqlMetricsDataSource | None = None
    admin_metrics: AdminMetricsService | None = None
    profile_admin: ProfileAdminService | None = None
    runtime_thresholds: RuntimeThresholds | None = None
    turns: SqlTurnStore | None = None
    runtime_timers: SqlRuntimeTimerStore | None = None
    business_connections: SqlBusinessConnectionStore | None = None
    persona_admin: PersonaAdminService | None = None
    backfill_queue: MemoryBackfillQueue | None = None
    backfill_wake: asyncio.Event | None = None
    # Evo-Agente Fase 0: shadow emotional detector (None when flag off).
    emotional_detector: EmotionalSignalDetector | None = None
    # Evo-Agente Fase 1: profile-synthesis trigger + service (None when flag off).
    profile_synthesis_trigger: ProfileSynthesisTriggerService | None = None
    profile_synthesis_service: ProfileSynthesisService | None = None
    # Evo-Agente Fase 0 repos exposed for the AgentDataPurgeJob (TTL by table).
    vip_profile_history_repo: SqlVipProfileHistoryRepo | None = None
    turn_category_log_repo: SqlTurnCategoryLogRepo | None = None
    emotional_signal_log_repo: SqlEmotionalSignalLogRepo | None = None
    # Evo-Agente Fase 2/3: pure classifier + mood engine (None when flag off);
    # vip_mood_state_repo exposed for the mood hook + future Fase 5 readers.
    turn_classifier: object | None = None
    mood_engine: object | None = None
    vip_mood_state_repo: SqlVipMoodStateRepo | None = None
    # Evo-Agente Fase 5: trust-budget service (built ALWAYS — consumed by
    # admin/profile_admin/thresholds even when the flag is off) + its repo.
    trust_budget: object | None = None
    vip_trust_budget_repo: SqlVipTrustBudgetRepo | None = None


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

    # Evo-Agente Fase 0: repos for the agent-evolution tables (schema-first).
    # Wired here because the detector (shadow writer) and the purge job need them.
    vip_profile_repo = SqlVipProfileRepo(sf)
    vip_profile_history_repo = SqlVipProfileHistoryRepo(sf)
    vip_mood_state_repo = SqlVipMoodStateRepo(sf)
    vip_trust_budget_repo = SqlVipTrustBudgetRepo(sf)
    turn_category_log_repo = SqlTurnCategoryLogRepo(sf)
    emotional_signal_repo = SqlEmotionalSignalLogRepo(sf)

    token = settings.telegram_bot_token.get_secret_value()
    bot_inst = bot or Bot(token=token)
    actuator = AiogramTelegramActuator(bot_inst)
    notifier = AiogramOwnerNotifier(
        bot_inst, owner_telegram_id=settings.owner_telegram_id
    )
    clock = SystemClock()
    # Evo-Agente Fase 5: the trust-budget service is built ALWAYS — admin
    # (correction event), profile_admin (ficha) and load_runtime_thresholds
    # consume it even when ``feature_trust_budget`` is off (the consumers gate
    # the wiring themselves with ``... if settings.feature_trust_budget else None``).
    trust_budget_service = TrustBudgetService(
        store=vip_trust_budget_repo,
        turn_category_log=turn_category_log_repo,
        clock=clock.now,
        initial=settings.trust_budget_initial,
        increment=settings.trust_budget_increment,
        decrement=settings.trust_budget_decrement,
        threshold=settings.trust_budget_threshold,
        dispersion_high=settings.trust_dispersion_high,
        trend_window_days=settings.trust_trend_window_days,
    )
    policy = delay_policy or RandomDelayPolicy(
        supervised_min=settings.delivery_supervised_delay_min,
        supervised_max=settings.delivery_supervised_delay_max,
        autonomous_min=settings.delivery_autonomous_delay_min,
        autonomous_max=settings.delivery_autonomous_delay_max,
        typing_per_char=settings.delivery_typing_per_char,
        typing_min=settings.delivery_typing_min_seconds,
        typing_max=settings.delivery_typing_max_seconds,
        pre_read_min=settings.delivery_pre_read_delay_min,
        pre_read_max=settings.delivery_pre_read_delay_max,
        post_read_min=settings.delivery_post_read_delay_min,
        post_read_max=settings.delivery_post_read_delay_max,
        inter_gap_min=settings.delivery_inter_message_gap_min,
        inter_gap_max=settings.delivery_inter_message_gap_max,
    )
    runtime_timers_store = SqlRuntimeTimerStore(sf)
    bc_store = SqlBusinessConnectionStore(sf)
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
        runtime_timer_store=runtime_timers_store,
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
    feature_staging_enabled = settings.feature_staging_enabled
    feature_general_mode_enabled = settings.feature_general_mode_enabled

    # GrayZoneService — created only when the feature is enabled.
    # When disabled, TurnOrchestrator receives None (dead-code guard).
    # staging_repo is shared with StagingService when both flags are on.
    gray_zone_repo: GrayZoneQueryRepo | None = None
    staging_repo: StagingCandidateRepo | None = None
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

    # H7: StagingService for owner corrections — only when feature_staging_enabled.
    if feature_staging_enabled:
        if staging_repo is None:
            staging_repo = StagingCandidateRepo(sf)
        staging = StagingService(
            staging_repo=staging_repo,
            examples_repo=examples_repo,
            policies_repo=policies_repo,
            sandbox=sandbox,
        )
    else:
        staging = None

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
        history=history,
        sandbox=sandbox,
    )

    from diana.application.approval_ui import ApprovalDraftVoider

    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,
        recontact=recontact,
        feature_recontact_enabled=feature_recontact_enabled,
        approval_ui=ApprovalDraftVoider(notifier),
        runtime_timers=runtime_timers_store,
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
        staging=staging,
        history=history,
        trust_budget=(
            trust_budget_service if settings.feature_trust_budget else None
        ),
    )

    catalog = get_persona_catalog()
    voz = catalog["voz_configurada"]

    # Item 2 — live persona catalog (hot-reload): the owner-admin service is
    # always wired; its runtime read (get_current_persona) is flag-gated, so
    # with the flag off the provider falls back to the static catalog and the
    # pipeline behaves exactly as before.
    persona_version_repo = PersonaVersionRepo(sf)
    daily_message_limit_repo = SqlDailyMessageLimitStore(sf)
    atencion_cycles = SqlAtencionCycleStore(sf)
    persona_admin_service = PersonaAdminService(
        payload_store=persona_version_repo,
        feature_persona_admin_enabled=settings.feature_persona_admin_enabled,
        owner_telegram_id=settings.owner_telegram_id,
        clock=clock.now,
    )
    persona_catalog_provider = PersonaCatalogProvider(
        persona_admin_service=persona_admin_service,
    )
    persona_admin_service.set_on_change(persona_catalog_provider.invalidate)

    # F2 Item 3: gate memory retrieval on the feature flag so the
    # ``feature_memory_enabled`` switch actually controls something.
    # Without this gate, the flag is a dead stub (see ROADMAP item 4.6).
    effective_memory_repo = (
        memories_repo if settings.feature_memory_enabled else None
    )
    if not settings.feature_memory_enabled:
        logger.info(
            "memory_feature_disabled",
            extra={"feature_memory_enabled": False},
        )
    registry = build_default_registry(
        history,
        memory_repo=effective_memory_repo,
        policy_repo=policies_repo,
        examples_repo=examples_repo,
        profile_repo=profiles_repo,
        embedding_service=embedding_svc,
        persona_facts=catalog["persona_facts"],
        voice_patterns=catalog["voice_patterns"],
        static_policies=catalog["policies"],
        schedule=catalog["schedule"],
        clock=clock,
        persona_catalog_provider=persona_catalog_provider,
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
        # DECISION DE PRODUCTO (2026-08-05): la escalación por preguntas
        # repetidas está DESACTIVADA — el bot responde siempre por el flujo
        # normal; el guard queda sin conexión (None) para reactivarlo basta
        # reponer RepetitionGuard(threshold=3).
        recent_intents=traces,
        repetition_guard=None,
        template_gate=template_gate,
        # Supervised naturalness redraft min (Director pre-Decider; not send gate).
        naturalness_min=float(DEFAULT_SUPERVISED_THRESHOLDS["naturalness_min"]),
        knowledge_augmenter=knowledge_augmenter,
        persona_catalog_provider=persona_catalog_provider,
    )

    learning = LearningService(traces)

    # F5 Pool 3 (F5-04): post-turn incremental extraction — built ALWAYS
    # (pattern Pool 2), injected into the orchestrator only when the flag is
    # ON. Flag OFF → memory_extraction=None → _maybe_post_turn no-op (A8).
    from diana.application.memory_extraction_service import MemoryExtractionService

    memory_extraction = MemoryExtractionService(
        feature_memory_enabled=settings.feature_memory_enabled,
        llm=provider,
        embedder=embedding_svc,
        history=history,
        turns=turns,
        memories=memories_repo,
        vips=vips,
        notifier=notifier,
        dedup_threshold=settings.backfill_dedup_threshold,
    )
    # Evo-Agente Fase 0: build the detector ALWAYS (pure constants); flag OFF
    # → emotional_detector=None → the orchestrator hook is a no-op (A8).
    detector = EmotionalSignalDetector()
    # Evo-Agente Fase 2/3: pure classifier + mood engine built ALWAYS (A8);
    # flag OFF → None injected → the orchestrator hooks are no-op (byte-identical).
    classifier = TurnClassifier(confidence_min=settings.classifier_confidence_min)
    mood = MoodEngine(
        return_rate=settings.mood_return_rate,
        signal_weight=settings.mood_signal_weight,
        axis_weights=settings.mood_axis_weights,
        noise=settings.mood_noise,
    )
    # Evo-Agente Fase 1 (A8): build the synthesis trigger + service ONLY when
    # the flag is on — flag OFF → both None → orchestrator hook and job no-op
    # (byte-identical to Fase 0). The staging repo is built here when the
    # synthesis flag is on but no staging/gray-zone feature created it (the
    # Fase 1 corrections source needs it).
    profile_synthesis_trigger: ProfileSynthesisTriggerService | None = None
    profile_synthesis_service: ProfileSynthesisService | None = None
    if settings.feature_profile_synthesis_enabled:
        # S9: trigger condition (d) — the emotional signal — requires the
        # emotional DETECTOR to be on. With it OFF the synthesis trigger still
        # evaluates volume / strong-signal / session_close, but the immediate
        # emotional path is inert. Logged (not silently coupled) so a shadow
        # run with the detector off is a documented partial trigger.
        if not settings.feature_emotional_detector_enabled:
            logger.info(
                "profile_synthesis_emotional_signal_source_unavailable",
                extra={
                    "reason": "feature_emotional_detector_enabled is False",
                    "effect": "condition (d) never fires; volume/strong-signal/"
                    "session_close still trigger",
                },
            )
        if staging_repo is None:
            staging_repo = StagingCandidateRepo(sf)
        profile_synthesis_service = ProfileSynthesisService(
            llm=provider,
            profile_store=vip_profile_repo,
            memories=memories_repo,
            corrections=staging_repo,
            confidence_min=settings.profile_synthesis_confidence_min,
        )
        profile_synthesis_trigger = ProfileSynthesisTriggerService(
            profile_reader=vip_profile_repo,
            activity=turns,
            volume_threshold=settings.profile_synthesis_volume_threshold,
            inactivity_minutes=settings.profile_synthesis_inactivity_minutes,
        )
    orchestrator = TurnOrchestrator(
        coordinator=coordinator,
        director=director,
        admin=admin,
        learning=learning,
        history=history,
        gray_zone=gray_zone,
        feature_gray_zone_enabled=feature_gray_zone_enabled,
        feature_general_mode_enabled=feature_general_mode_enabled,
        behavior=behavior,
        autonomous_mode=ams,
        vip_store=vips,
        traces=traces,
        delivery_mode=settings.global_mode,
        feature_advanced_behavior=feature_advanced_behavior,
        sandbox=sandbox,
        delay_policy=policy,
        runtime_timers=runtime_timers_store,
        clock=clock,
        daily_message_limit_store=daily_message_limit_repo,
        turns=turns,
        persona_catalog_provider=persona_catalog_provider,
        trace_reader=traces,
        atencion_cycles=atencion_cycles,
        memory_extraction=(
            memory_extraction if settings.feature_memory_enabled else None
        ),
        emotional_detector=(
            detector if settings.feature_emotional_detector_enabled else None
        ),
        emotional_signal_log=emotional_signal_repo,
        profile_synthesis_trigger=(
            profile_synthesis_trigger
            if settings.feature_profile_synthesis_enabled
            else None
        ),
        turn_classifier=(
            classifier if settings.feature_phatic_autonomy else None
        ),
        turn_category_log=turn_category_log_repo,
        mood_engine=(mood if settings.feature_mood_engine else None),
        vip_mood_state=vip_mood_state_repo,
        trust_budget=(
            trust_budget_service if settings.feature_trust_budget else None
        ),
    )

    # REQ-MEM-07: supervised-approved turns must run the SAME post-turn
    # learning + memory extraction as the autonomous path. AdminService is
    # built BEFORE the orchestrator (line ~503), so the hook is injected via a
    # setter now that the orchestrator exists. ``_maybe_post_turn`` is wired
    # unconditionally — it internally skips sandbox, runs the learning hook and
    # no-ops the memory extraction when the flag is OFF (memory_extraction=None,
    # A8), matching the autonomous-path behaviour byte-for-byte.
    admin.set_post_turn_hook(orchestrator._maybe_post_turn)

    # Forbidden keywords loaded at boot (async load deferred to startup helper).
    forbidden_keywords: list[str] = []
    sessions = CorrectSessionStore()

    # Doctrine router — only wired when gray zone feature is enabled.
    doctrine_router = (
        build_doctrine_router(
            gray_zone=gray_zone,
            coordinator=coordinator,
            owner_telegram_id=settings.owner_telegram_id,
            admin=admin,
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
        feature_general_mode_enabled=feature_general_mode_enabled,
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
        # F5 Pool 4 (F5-06): semantic memory section of the ficha — only
        # wired with the flag ON (flag OFF → None → no query, byte-identical).
        memories=(memories_repo if settings.feature_memory_enabled else None),
        # Evo-Agente Fase 5 (EA-06): 🔐 Confianza section of the ficha — only
        # wired with the flag ON (flag OFF → None → no query, byte-identical).
        trust_budget=(
            trust_budget_service if settings.feature_trust_budget else None
        ),
    )

    # VIP DM history seed (Telethon personal session) — optional until env is set.
    history_seed = _build_vip_history_seed(
        settings, history=history, notifier=notifier
    )

    # F5 Pool 2: backfill queue + scheduler (one window per cycle, interval-gated).
    # The service wires the chat↔vip binding (vips), the semantic dedup reader
    # and profile-presence (memories_repo) that Pool 1 left optional; the queue
    # is built ALWAYS but gated by the flag (enqueue no-op + routers get None
    # when OFF → hidden button, inert actions).
    from diana.application.memory_backfill_service import MemoryBackfillService
    from diana.application.memory_approval_service import MemoryApprovalService
    from diana.infrastructure.db.repositories.backfill_queue import (
        SqlBackfillQueueRepo,
    )

    backfill_service = MemoryBackfillService(
        feature_memory_enabled=settings.feature_memory_enabled,
        history=history,
        llm=provider,
        memories=memories_repo,
        embedder=embedding_svc,
        notifier=notifier,
        vips=vips,
        dedup=memories_repo,
        profile_presence=memories_repo,
        dedup_threshold=settings.backfill_dedup_threshold,
        clock=clock.now,
    )
    backfill_wake = asyncio.Event()
    backfill_queue = MemoryBackfillQueue(
        enabled=settings.feature_memory_enabled,
        store=SqlBackfillQueueRepo(sf),
        backfill=backfill_service,
        vips=vips,
        history=history,
        memories=memories_repo,
        notifier=notifier,
        window_size=200,
        max_attempts=3,
        wake=backfill_wake,
        clock=clock.now,
    )

    # F5 Pool 4 (F5-05): owner approval of pending_owner facts — built
    # ALWAYS (pattern Pool 2), gated at the dispatcher (flag OFF → None →
    # inert router, byte-identical). vips enriches the DM list with names.
    memory_approval = MemoryApprovalService(
        memories=memories_repo,
        vips=vips,
        owner_telegram_id=settings.owner_telegram_id,
    )

    from diana.application.draft_variants import DraftVariantService

    draft_variants = DraftVariantService(
        approvals=approvals,
        turns=turns,
        director=director,
        notifier=notifier,
        owner_telegram_id=settings.owner_telegram_id,
        history=history,
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
        gray_zone=gray_zone,
        staging=staging,
        admin_trace=admin_trace,
        admin_metrics=admin_metrics,
        profile_admin=profile_admin,
        persona_admin=persona_admin_service,
        feature_persona_admin_enabled=settings.feature_persona_admin_enabled,
        promo=promo,
        feature_promo_enabled=feature_promo_enabled,
        feature_general_mode_enabled=feature_general_mode_enabled,
        sandbox=sandbox,
        training_mode=config_store,
        config_store=config_store,
        atencion_cycles=atencion_cycles,
        rate_limit_max_events=settings.rate_limit_max_events,
        rate_limit_window_s=settings.rate_limit_window_s,
        dedup_ttl_s=settings.dedup_ttl_s,
        bc_store=bc_store,
        history_seed=history_seed,
        draft_variants=draft_variants,
        history=history,
        backfill_queue=(
            backfill_queue if settings.feature_memory_enabled else None
        ),
        memory_approval=(
            memory_approval if settings.feature_memory_enabled else None
        ),
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
        metrics_data=metrics_data,
        admin_metrics=admin_metrics,
        profile_admin=profile_admin,
        runtime_thresholds=runtime_thresholds,
        persona_admin=persona_admin_service,
        turns=turns,
        runtime_timers=runtime_timers_store,
        business_connections=bc_store,
        backfill_queue=backfill_queue,
        backfill_wake=backfill_wake,
        emotional_detector=(
            detector if settings.feature_emotional_detector_enabled else None
        ),
        profile_synthesis_trigger=profile_synthesis_trigger,
        profile_synthesis_service=profile_synthesis_service,
        vip_profile_history_repo=vip_profile_history_repo,
        turn_category_log_repo=turn_category_log_repo,
        emotional_signal_log_repo=emotional_signal_repo,
        turn_classifier=(
            classifier if settings.feature_phatic_autonomy else None
        ),
        mood_engine=(mood if settings.feature_mood_engine else None),
        vip_mood_state_repo=vip_mood_state_repo,
        trust_budget=trust_budget_service,
        vip_trust_budget_repo=vip_trust_budget_repo,
    )


async def load_forbidden_keywords(app: AppContainer) -> list[str]:
    """Load keywords from system_config into the container (boot-time).

    Strips H6 TemplateGate-owned annex phrases (e.g. legacy seed ``eres un bot``)
    so they never silent-escalate as palabra_prohibida.
    """
    from diana.telegram.middlewares.forbidden import sanitize_forbidden_keywords

    store = SqlSystemConfigStore(app.session_factory)
    kws = sanitize_forbidden_keywords(await store.get_forbidden_keywords())
    app.forbidden_keywords.clear()
    app.forbidden_keywords.extend(kws)
    # Explicit setter — no Dispatcher graph walk.
    app.wiring.forbidden_middleware.set_keywords(kws)
    logger.info("forbidden_keywords_loaded", extra={"count": len(kws)})
    return kws



async def load_runtime_thresholds(app: AppContainer) -> None:
    """Hydrate RuntimeThresholds + emotional detector thresholds at boot (R2 residual).

    Calibration writes DB + live holder; boot must re-read DB so mins survive restart.
    Missing keys leave pure DEFAULT_* / safety from RuntimeThresholds defaults.

    The emotional detector override is independent of the RuntimeThresholds
    holder: it is applied whenever ``app.emotional_detector`` is wired (manual
    override only, never auto-calibrated) and runs LAST (plan Task 4 "al
    final"). The holder-None path keeps its pre-item no-op semantics for the
    holder queries (no I/O there); only the detector override does its own
    single read on the wired path.
    """
    store = SqlSystemConfigStore(app.session_factory)

    holder = app.runtime_thresholds
    if holder is not None:
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

    # Evo-Agente Fase 0: manual override of the detector thresholds from
    # system_config key ``emotional_detector`` — at the END of the method
    # (plan Task 4). Detector None (flag off) → no-op WITHOUT any DB I/O on
    # the non-wired path. A transient DB error must not break boot — read is
    # best-effort.
    detector = getattr(app, "emotional_detector", None)
    if detector is not None:
        try:
            cfg = await store.get("emotional_detector")
        except Exception:
            logger.exception("emotional_detector_thresholds_read_failed")
            cfg = None
        if isinstance(cfg, dict):
            detector.apply_overrides(cfg)
            logger.info(
                "emotional_detector_thresholds_loaded",
                extra={
                    "synthesis_threshold": detector.synthesis_threshold,
                    "escalate_threshold": detector.escalate_threshold,
                    "min_baseline_turns": detector.min_baseline_turns,
                },
            )

    # Evo-Agente Fase 1: manual override of the profile-synthesis thresholds
    # from system_config key ``profile_synthesis`` (same best-effort pattern as
    # the detector). Both wired (flag on) → apply; either None → no-op without
    # any DB I/O on the non-wired path. A transient DB error must not break
    # boot. Override is manual ONLY — never auto-calibrated.
    trigger = getattr(app, "profile_synthesis_trigger", None)
    service = getattr(app, "profile_synthesis_service", None)
    if trigger is not None and service is not None:
        try:
            cfg = await store.get("profile_synthesis")
        except Exception:
            logger.exception("profile_synthesis_thresholds_read_failed")
            cfg = None
        if isinstance(cfg, dict):
            trigger.apply_overrides(cfg)
            service.apply_overrides(cfg)
            logger.info(
                "profile_synthesis_thresholds_loaded",
                extra={
                    # Fix round nit: direct attribute access (both are wired
                    # and non-None here) instead of defensive getattr on
                    # private names.
                    "volume_threshold": trigger._volume_threshold,  # noqa: SLF001
                    "inactivity_minutes": trigger._inactivity_minutes,  # noqa: SLF001
                    "confidence_min": service._confidence_min,  # noqa: SLF001
                },
            )

    # Evo-Agente Fase 2: manual override of the classifier thresholds from
    # system_config key ``phatic_classifier`` (same best-effort pattern).
    # The classifier is always built but only WIRED (flag on) → override
    # applies only when the phatic hook is active. Never auto-calibrated.
    classifier = getattr(app, "turn_classifier", None)
    if classifier is not None:
        try:
            cfg = await store.get("phatic_classifier")
        except Exception:
            logger.exception("phatic_classifier_thresholds_read_failed")
            cfg = None
        if isinstance(cfg, dict):
            classifier.apply_overrides(cfg)
            logger.info(
                "phatic_classifier_thresholds_loaded",
                extra={"confidence_min": classifier._confidence_min},  # noqa: SLF001
            )
    else:
        # Review round 1 nit: a ``phatic_classifier`` config (if any) is not
        # applied when the feature is OFF — surface it so a misconfig is not
        # silently dropped (no DB read on the non-wired path).
        logger.info(
            "phatic_classifier_thresholds_skipped",
            extra={"reason": "turn_classifier not wired (feature_phatic_autonomy off)"},
        )

    # Evo-Agente Fase 3: manual override of the mood-engine thresholds from
    # system_config key ``mood_engine`` (same pattern). Never auto-calibrated.
    mood = getattr(app, "mood_engine", None)
    if mood is not None:
        try:
            cfg = await store.get("mood_engine")
        except Exception:
            logger.exception("mood_engine_thresholds_read_failed")
            cfg = None
        if isinstance(cfg, dict):
            mood.apply_overrides(cfg)
            logger.info(
                "mood_engine_thresholds_loaded",
                extra={
                    "return_rate": mood._return_rate,  # noqa: SLF001
                    "signal_weight": mood._signal_weight,  # noqa: SLF001
                    "noise": mood._noise,  # noqa: SLF001
                },
            )
    else:
        # Review round 1 nit: same skip visibility for the ``mood_engine`` key.
        logger.info(
            "mood_engine_thresholds_skipped",
            extra={"reason": "mood_engine not wired (feature_mood_engine off)"},
        )

    # Evo-Agente Fase 5: manual override of the trust-budget thresholds from
    # system_config key ``trust_budget`` (same best-effort pattern). The
    # service is built ALWAYS (AppContainer.trust_budget); the overrides apply
    # regardless of the feature flag so a manual calibration survives a toggle.
    # Override is manual ONLY — never auto-calibrated.
    tb = getattr(app, "trust_budget", None)
    if tb is not None:
        try:
            cfg = await store.get("trust_budget")
        except Exception:
            logger.exception("trust_budget_thresholds_read_failed")
            cfg = None
        if isinstance(cfg, dict):
            tb.apply_overrides(cfg)
            logger.info(
                "trust_budget_thresholds_loaded",
                extra={
                    "initial": tb._initial,  # noqa: SLF001
                    "increment": tb._increment,  # noqa: SLF001
                    "decrement": tb._decrement,  # noqa: SLF001
                    "threshold": tb._threshold,  # noqa: SLF001
                    "dispersion_high": tb._dispersion_high,  # noqa: SLF001
                },
            )
    else:
        logger.info(
            "trust_budget_thresholds_skipped",
            extra={"reason": "trust_budget not wired"},
        )


async def run_app_startup_recovery(app: AppContainer) -> Any:
    """Expire mid-flight deliveries; recover fresh ones; re-notify approvals.

    Also recovers zombie turns, re-materializes drafts from traces, and
    recovers active **delivery** runtime timers when the respective stores
    are available. VIP ``pre_delay`` timers are resumed later via
    ``run_app_pre_delay_recovery`` (after missed updates).
    """
    return await run_startup_recovery(
        deliveries=app.deliveries,
        approvals=app.approvals,
        notifier=app.notifier,
        clock=app.clock,
        stale_after=DEFAULT_STALE_AFTER,
        behavior=app.behavior,
        vips=app.vips,
        global_mode=app.settings.global_mode,
        turns=app.turns,
        traces=app.trace_store,
        timers=app.runtime_timers,
        promo=app.promo,
    )


async def run_app_pre_delay_recovery(app: AppContainer) -> int:
    """Resume VIP waiting_delay after missed-update recovery (D1)."""
    from diana.application.recovery_startup import resume_pre_delay_timers

    if app.runtime_timers is None or app.turns is None:
        return 0
    count = await resume_pre_delay_timers(
        timers=app.runtime_timers,
        turns=app.turns,
        orchestrator=app.orchestrator,
        clock=app.clock,
    )
    if count:
        try:
            await app.notifier.notify_info(
                f"Recuperacion: {count} espera(s) VIP reanudada(s) tras reinicio"
            )
        except Exception:
            logger.exception("pre_delay_recovery_notify_failed")
    return count


__all__ = [
    "AppContainer",
    "DEFAULT_PERSONA",
    "RandomDelayPolicy",
    "SystemClock",
    "TurnStoreStatusReader",
    "build_app",
    "load_forbidden_keywords",
    "load_runtime_thresholds",
    "run_app_pre_delay_recovery",
    "run_app_startup_recovery",
]
