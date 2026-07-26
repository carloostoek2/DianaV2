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
