"""Regression: composition root must wire status_sink as an object with .transition."""

from __future__ import annotations

from pathlib import Path

import pytest

import diana


@pytest.fixture
def _comp_src() -> str:
    root = Path(diana.__file__).resolve().parent
    return (root / "composition.py").read_text(encoding="utf-8")


def test_composition_status_sink_is_coordinator_not_method(_comp_src: str) -> None:
    """Director expects TurnStatusSink.transition; a method object has no .transition."""
    assert "status_sink=coordinator.transition_sink" not in _comp_src
    assert "status_sink=coordinator" in _comp_src


def test_composition_gray_zone_wired_to_orchestrator(_comp_src: str) -> None:
    """Orchestrator receives gray_zone and feature_gray_zone_enabled."""
    assert "gray_zone=gray_zone" in _comp_src
    assert "feature_gray_zone_enabled=feature_gray_zone_enabled" in _comp_src


def test_composition_gray_zone_service_conditional(_comp_src: str) -> None:
    """GrayZoneService is only created when feature_gray_zone_enabled is True."""
    assert "if feature_gray_zone_enabled:" in _comp_src
    assert "gray_zone = GrayZoneService(" in _comp_src


def test_composition_decider_receives_feature_flags(_comp_src: str) -> None:
    """Decider is wired with gray-zone + autonomous flags and thresholds."""
    assert "feature_gray_zone_enabled=" in _comp_src
    assert "feature_autonomous_mode=" in _comp_src
    assert "autonomous_thresholds=" in _comp_src
    assert "Decider(" in _comp_src
    # Ensure gray-zone kw still present on Decider construction path.
    assert "feature_gray_zone_enabled=feature_gray_zone_enabled" in _comp_src
    assert "feature_autonomous_mode=feature_autonomous_mode" in _comp_src


def test_composition_ams_wired_to_orchestrator(_comp_src: str) -> None:
    """AutonomousModeService is constructed and injected into TurnOrchestrator."""
    assert "AutonomousModeService(" in _comp_src
    assert "autonomous_mode=" in _comp_src
    assert "from diana.application.autonomous_mode_service import AutonomousModeService" in _comp_src
    assert "DEFAULT_AUTONOMOUS_THRESHOLDS" in _comp_src


def test_composition_orchestrator_receives_autonomous_deps(_comp_src: str) -> None:
    """Orch gets behavior, vip_store, traces, delivery_mode for send path."""
    assert "behavior=behavior" in _comp_src
    assert "vip_store=vips" in _comp_src
    assert "traces=traces" in _comp_src
    assert "delivery_mode=" in _comp_src


def test_composition_load_feature_flags_removed(_comp_src: str) -> None:
    """load_feature_flags was removed per BUG-1 (option b)."""
    assert "def load_feature_flags" not in _comp_src


def test_composition_admin_trace_wired(_comp_src: str) -> None:
    """admin_trace is instantiated and passed to build_dispatcher."""
    assert "admin_trace = AdminTraceService(" in _comp_src
    assert "admin_trace=admin_trace" in _comp_src


def test_composition_advanced_behavior_wired(_comp_src: str) -> None:
    """FEATURE_ADVANCED_BEHAVIOR reaches BehaviorEngine, AdminService, TurnOrchestrator."""
    assert "feature_advanced_behavior = settings.feature_advanced_behavior" in _comp_src
    assert "feature_advanced_behavior=feature_advanced_behavior" in _comp_src
    assert "BehaviorEngine(" in _comp_src
    # Engine gets advanced kill-switch + prod quirk probability when flag on.
    assert "quirk_probability=" in _comp_src
    # Orch + admin builders receive the same flag for DeliveryContext allow_*.
    assert "AdminService(" in _comp_src
    assert "TurnOrchestrator(" in _comp_src
    # Count assignments into the three consumers (engine, admin, orch).
    assert _comp_src.count("feature_advanced_behavior=feature_advanced_behavior") >= 3
    # SEC-F1: Admin freeze gate needs vip_store wired.
    assert "vip_store=vips" in _comp_src


def test_composition_promo_service_wired(_comp_src: str) -> None:
    """PromoService is constructed and passed into Auth via build_dispatcher."""
    assert "from diana.application.promo_service import PromoService" in _comp_src
    assert "PromoTriggerRepo" in _comp_src
    assert "PromoExecutionRepo" in _comp_src
    assert "PromoService(" in _comp_src
    assert "feature_promo_enabled = settings.feature_promo_enabled" in _comp_src
    assert "feature_promo_enabled=feature_promo_enabled" in _comp_src
    assert "promo=promo" in _comp_src
    assert "promo=promo," in _comp_src or "promo=promo\n" in _comp_src


def test_setup_auth_receives_promo_kwargs() -> None:
    """build_dispatcher forwards promo + feature flag into AuthMiddleware."""
    from pathlib import Path

    import diana

    root = Path(diana.__file__).resolve().parent
    setup_src = (root / "telegram" / "setup.py").read_text(encoding="utf-8")
    assert "promo: PromoService | None = None" in setup_src
    assert "feature_promo_enabled: bool = False" in setup_src
    assert "promo=promo" in setup_src
    assert "feature_promo_enabled=feature_promo_enabled" in setup_src
    assert "AuthMiddleware(" in setup_src


def test_composition_app_container_has_promo_field() -> None:
    from diana.composition import AppContainer

    assert "promo" in AppContainer.__dataclass_fields__


def test_composition_recontact_service_wired(_comp_src: str) -> None:
    """RecontactService + schedule repo always constructed; flag from settings."""
    assert "from diana.application.recontact_service import" in _comp_src
    assert "RecontactService" in _comp_src
    assert "RecontactScheduleRepo" in _comp_src
    assert "feature_recontact_enabled" in _comp_src
    assert "feature_recontact_enabled=settings.feature_recontact_enabled" in _comp_src or (
        "feature_recontact_enabled=feature_recontact_enabled" in _comp_src
    )
    assert "recontact=recontact" in _comp_src or "recontact=recontact," in _comp_src


def test_composition_app_container_has_recontact_field() -> None:
    from diana.composition import AppContainer

    assert "recontact" in AppContainer.__dataclass_fields__


def test_composition_turn_coordinator_receives_recontact(_comp_src: str) -> None:
    """BR-07: TurnCoordinator gets recontact service + feature flag."""
    assert "from diana.application.recontact_service import" in _comp_src
    assert "RecontactService" in _comp_src
    # Coordinator construction must pass both kwargs (not bare 3-arg form only).
    assert "recontact=recontact" in _comp_src
    assert "feature_recontact_enabled=feature_recontact_enabled" in _comp_src
    # Build order: RecontactService constructed before TurnCoordinator.
    recontact_pos = _comp_src.find("recontact = RecontactService(")
    coord_pos = _comp_src.find("coordinator = TurnCoordinator(")
    assert recontact_pos != -1
    assert coord_pos != -1
    assert recontact_pos < coord_pos
    # Within TurnCoordinator(...) block both kwargs appear.
    coord_block = _comp_src[coord_pos : coord_pos + 400]
    assert "recontact=recontact" in coord_block
    assert "feature_recontact_enabled=feature_recontact_enabled" in coord_block


def test_composition_calibration_service_wired(_comp_src: str) -> None:
    """CalibrationService + SQL data source; flag from settings."""
    assert "from diana.application.calibration_service import CalibrationService" in _comp_src
    assert "SqlCalibrationDataSource" in _comp_src
    assert "CalibrationService(" in _comp_src
    assert "feature_calibration_enabled" in _comp_src
    assert "feature_calibration_enabled=settings.feature_calibration_enabled" in _comp_src or (
        "feature_calibration_enabled=feature_calibration_enabled" in _comp_src
    )
    # Reuse EmbeddingService already constructed for registry.
    assert "embeddings=embedding_svc" in _comp_src or "embeddings=embedding" in _comp_src


def test_composition_metrics_aggregation_wired(_comp_src: str) -> None:
    """MetricsAggregationService + SqlMetricsDataSource + learning metrics repo."""
    assert (
        "from diana.application.metrics_service import MetricsAggregationService"
        in _comp_src
    )
    assert "SqlMetricsDataSource" in _comp_src
    assert "SqlLearningMetricsRepo" in _comp_src
    assert "MetricsAggregationService(" in _comp_src
    # Drift detector is CalibrationService (detect_drift readable even if flag off).
    assert "drift=calibration" in _comp_src


def test_composition_admin_metrics_wired(_comp_src: str) -> None:
    """AdminMetricsService built from learning metrics store and passed to dispatcher."""
    assert (
        "from diana.application.admin_metrics_service import AdminMetricsService"
        in _comp_src
    )
    assert "AdminMetricsService(" in _comp_src
    assert "admin_metrics=admin_metrics" in _comp_src


def test_composition_profile_admin_wired(_comp_src: str) -> None:
    """ProfileAdminService constructed and forwarded into the dispatcher."""
    assert "ProfileAdminService(" in _comp_src
    assert "profile_admin=" in _comp_src
    assert (
        "from diana.application.profile_admin_service import ProfileAdminService"
        in _comp_src
    )


def test_composition_app_container_has_pool3_fields() -> None:
    from diana.composition import AppContainer

    fields = AppContainer.__dataclass_fields__
    assert "calibration" in fields
    assert "metrics" in fields
    assert "admin_metrics" in fields


def test_setup_forwards_admin_metrics() -> None:
    """build_dispatcher forwards admin_metrics into admin + callback routers."""
    from pathlib import Path

    import diana

    root = Path(diana.__file__).resolve().parent
    setup_src = (root / "telegram" / "setup.py").read_text(encoding="utf-8")
    assert "admin_metrics" in setup_src
    assert "admin_metrics: AdminMetricsService | None = None" in setup_src
    assert "admin_metrics=admin_metrics" in setup_src
    assert setup_src.count("admin_metrics=admin_metrics") >= 2


def test_composition_load_runtime_thresholds_exported(_comp_src: str) -> None:
    assert "async def load_runtime_thresholds" in _comp_src
    assert "runtime_thresholds=runtime_thresholds" in _comp_src


def test_main_calls_load_runtime_thresholds() -> None:
    from pathlib import Path

    main = Path("src/diana/main.py").read_text(encoding="utf-8")
    assert "load_runtime_thresholds" in main
    assert "await load_runtime_thresholds(app)" in main


def test_composition_passes_ops_middleware_knobs(_comp_src: str) -> None:
    """SUG-1: Settings rate/dedup knobs reach build_dispatcher."""
    assert "rate_limit_max_events=settings.rate_limit_max_events" in _comp_src
    assert "rate_limit_window_s=settings.rate_limit_window_s" in _comp_src
    assert "dedup_ttl_s=settings.dedup_ttl_s" in _comp_src



def test_composition_persona_catalog_wired(_comp_src: str) -> None:
    """J.1/H2: composition loads catalog and wires style_rules + catalogs."""
    assert "get_persona_catalog" in _comp_src
    assert "style_rules=" in _comp_src
    assert "persona_facts=" in _comp_src
    assert "voice_patterns=" in _comp_src
    assert "static_policies=" in _comp_src
    # English placeholder must not be used as production persona assignment.
    assert "warm and professional VIP chat assistant" not in _comp_src
    # Lazy: no bare load_persona_catalog() at module import path for catalog
    assert "_PERSONA_CATALOG = load_persona_catalog()" not in _comp_src


def test_composition_schedule_and_clock_wired(_comp_src: str) -> None:
    """H9: composition passes schedule catalog slice + SystemClock to registry."""
    assert "schedule=" in _comp_src
    assert 'catalog["schedule"]' in _comp_src or "catalog['schedule']" in _comp_src
    assert "clock=" in _comp_src
    assert "SystemClock" in _comp_src


def test_composition_profiles_repo_wired(_comp_src: str) -> None:
    """Item4: ProfilesRepo constructed and passed as profile_repo= to registry."""
    assert (
        "from diana.infrastructure.db.repositories.profiles import ProfilesRepo"
        in _comp_src
    )
    assert "profiles_repo = ProfilesRepo(sf)" in _comp_src
    assert "profile_repo=profiles_repo" in _comp_src
    # Not injected into SandboxService (writer residual / PLAN OOS).
    sandbox_idx = _comp_src.find("SandboxService(")
    if sandbox_idx != -1:
        sandbox_block = _comp_src[sandbox_idx : sandbox_idx + 200]
        assert "profile" not in sandbox_block.lower()

def test_composition_repetition_guard_wired(_comp_src: str) -> None:
    """H4/H5: Director receives recent_intents=traces + RepetitionGuard(3)."""
    assert "from diana.cognitive.repetition_guard import RepetitionGuard" in _comp_src
    assert "recent_intents=traces" in _comp_src
    assert "RepetitionGuard(threshold=3)" in _comp_src
    assert "repetition_guard=RepetitionGuard(threshold=3)" in _comp_src


def test_composition_template_gate_wired(_comp_src: str) -> None:
    """H6: Director receives TemplateGate with deteccion_ia before saludo_constante."""
    assert "from diana.cognitive.template_gate import TemplateGate, TemplateRule" in _comp_src
    assert 'id="deteccion_ia"' in _comp_src
    assert 'id="saludo_constante"' in _comp_src
    assert "template_gate=" in _comp_src
    assert "TemplateGate(rules=" in _comp_src
    # Rule order: deteccion_ia constructed/listed before saludo in rules list
    ia_pos = _comp_src.find('id="deteccion_ia"')
    saludo_pos = _comp_src.find('id="saludo_constante"')
    assert ia_pos != -1 and saludo_pos != -1
    assert ia_pos < saludo_pos
    rules_list_pos = _comp_src.find("TemplateGate(rules=")
    assert rules_list_pos != -1
    rules_block = _comp_src[rules_list_pos : rules_list_pos + 120]
    assert "deteccion_ia" in rules_block
    assert "saludo_constante" in rules_block
    assert rules_block.find("deteccion_ia") < rules_block.find("saludo_constante")


def test_persona_reglas_estilo_no_j2_examples_note() -> None:
    """H6.6.5: persona JSON style rules drop the (ver J.2 / examples) note."""
    import json
    from pathlib import Path

    import diana

    path = Path(diana.__file__).resolve().parent / "config" / "persona_diana.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data["voz_configurada"]["reglas_estilo"]
    joined = " ".join(rules)
    assert "(ver J.2 / examples)" not in joined
    assert any("expresión característica de voz" in r for r in rules)


def test_setup_forbidden_middleware_still_accepts_behavior_kw() -> None:
    """Legacy residual: setup still passes behavior= to Forbidden (unused after H6).

    IA template deliver no longer runs in middleware; param kept for API
    stability until residual cleanup of handle_deterministic_template_escalate.
    """
    from pathlib import Path

    import diana

    root = Path(diana.__file__).resolve().parent
    setup_src = (root / "telegram" / "setup.py").read_text(encoding="utf-8")
    assert "ForbiddenKeywordsMiddleware(" in setup_src
    block_start = setup_src.find("ForbiddenKeywordsMiddleware(")
    block = setup_src[block_start : block_start + 350]
    # Still wired (dead for IA path); not a claim that IA auto-deliver is live.
    assert "behavior=behavior" in block





def test_composition_sandbox_wired(_comp_src: str) -> None:
    """When feature_sandbox_enabled, SandboxService + augmenter + deps are wired."""
    assert "sandbox = SandboxService() if feature_sandbox_enabled else None" in _comp_src
    assert "SandboxKnowledgeAugmenter" in _comp_src
    assert "knowledge_augmenter=" in _comp_src
    # Admin + orch + dispatcher receive sandbox
    assert "sandbox=sandbox" in _comp_src
    assert _comp_src.count("sandbox=sandbox") >= 3


def test_composition_admin_receives_staging_when_enabled(_comp_src: str) -> None:
    """H7: StagingService is flag-gated and injected into Admin with history."""
    assert (
        "from diana.application.staging_service import StagingService" in _comp_src
    )
    assert "feature_staging_enabled = settings.feature_staging_enabled" in _comp_src
    assert "if feature_staging_enabled:" in _comp_src
    assert "StagingService(" in _comp_src
    assert "staging = None" in _comp_src  # flag off path
    assert "staging=staging" in _comp_src
    assert "history=history" in _comp_src
    # Admin construction region receives both deps.
    admin_start = _comp_src.find("admin = AdminService(")
    assert admin_start != -1
    admin_block = _comp_src[admin_start : admin_start + 700]
    assert "staging=staging" in admin_block
    assert "history=history" in admin_block


def test_setup_auth_and_admin_receive_sandbox() -> None:
    from pathlib import Path
    import diana

    root = Path(diana.__file__).resolve().parent
    setup_src = (root / "telegram" / "setup.py").read_text(encoding="utf-8")
    assert "sandbox" in setup_src
    assert "AuthMiddleware(" in setup_src
    assert "sandbox=sandbox" in setup_src
    assert "build_admin_router(" in setup_src



def test_composition_recontact_sandbox_hook(_comp_src: str) -> None:
    """RecontactService must bind is_sandbox_vip from SandboxService sessions."""
    assert "is_sandbox_vip=None" not in _comp_src
    assert "is_sandbox_vip=" in _comp_src
    assert "sandbox.is_active" in _comp_src


def test_composition_recontact_history_and_sandbox_wired(_comp_src: str) -> None:
    """Recontact owner history residual: inject history + sandbox into RecontactService."""
    start = _comp_src.find("recontact = RecontactService(")
    assert start != -1
    # Bound the constructor call block (until next top-level assignment-ish).
    block = _comp_src[start : start + 900]
    assert "history=history" in block
    assert "sandbox=sandbox" in block
