"""Env-driven application settings. Secrets never live in the repository."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata",
        "169.254.169.254",
    }
)


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables / .env file.

    Secrets use SecretStr so repr/model_dump do not leak tokens by default.
    Call ``.get_secret_value()`` only at I/O boundaries (Telegram, DB, HTTP).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: SecretStr
    owner_telegram_id: Annotated[int, Field(gt=0)]
    database_url: SecretStr  # must be postgresql+asyncpg://...
    deepseek_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.deepseek.com"
    # Boot-time default model; the owner can switch it at runtime via the
    # admin surface (ADM-03, system_config key "llm") without a restart.
    llm_model: str = "deepseek-v4-flash"
    # DeepSeek v4 "thinking" (chain-of-thought) for free-text drafts only.
    # Structured JSON nodes (Analyst/Evaluator) always keep thinking off.
    # Default on: better draft quality; raise max_tokens budget via provider.
    llm_thinking_enabled: bool = True
    # Privacy: personal identifiers (emails, phones, payment cards, @handles,
    # URLs) are masked before any outbound LLM call and restored on the reply.
    # Default ON (privacy-first): masking is behavior-transparent because the
    # reply is unmasked before it reaches the VIP or is persisted. Disable only
    # for debugging — this is the one flag that defaults to safe.
    feature_pii_masking_enabled: bool = True
    global_mode: Literal["supervised", "autonomous", "fake_delivery"] = "supervised"
    delivery_max_send_attempts: Annotated[int, Field(ge=1, le=10)] = 3
    delivery_retry_backoff_seconds: Annotated[float, Field(gt=0)] = 0.05
    # Human-like pre-send wait (REQ-HUM-01/04). Seconds.
    # Supervised: fixed 2 min (min=max). Autonomous: randomized 3–8 min.
    delivery_supervised_delay_min: Annotated[float, Field(gt=0)] = 120.0
    delivery_supervised_delay_max: Annotated[float, Field(gt=0)] = 120.0
    delivery_autonomous_delay_min: Annotated[float, Field(gt=0)] = 180.0
    delivery_autonomous_delay_max: Annotated[float, Field(gt=0)] = 480.0
    # Micro-delays for humanized delivery cadence (REQ-HUM-01/04).
    delivery_typing_per_char: Annotated[float, Field(gt=0)] = 0.125     # 8 chars/sec
    delivery_typing_min_seconds: Annotated[float, Field(gt=0)] = 2.0
    delivery_typing_max_seconds: Annotated[float, Field(gt=0)] = 15.0
    delivery_pre_read_delay_min: Annotated[float, Field(gt=0)] = 0.3
    delivery_pre_read_delay_max: Annotated[float, Field(gt=0)] = 1.0
    delivery_post_read_delay_min: Annotated[float, Field(gt=0)] = 1.5
    delivery_post_read_delay_max: Annotated[float, Field(gt=0)] = 4.0
    delivery_inter_message_gap_min: Annotated[float, Field(gt=0)] = 1.5
    delivery_inter_message_gap_max: Annotated[float, Field(gt=0)] = 3.0
    trace_ttl_days: Annotated[int, Field(ge=1)] = 30
    log_level: LogLevel = "INFO"

    # F2 feature flag static defaults (runtime reading via SqlSystemConfigStore is Item 3).
    feature_memory_enabled: bool = False
    feature_context_enabled: bool = False
    # TTL (hours) for interpreted context snapshots (REQ-MEM-06 contexts table).
    context_ttl_hours: int = 24
    feature_gray_zone_enabled: bool = False
    feature_staging_enabled: bool = False
    feature_sandbox_enabled: bool = False

    # F3 feature flag static defaults (runtime DB merge is a later item).
    feature_autonomous_mode: bool = False
    feature_recontact_enabled: bool = False
    feature_promo_enabled: bool = False
    feature_calibration_enabled: bool = False
    feature_advanced_behavior: bool = False
    feature_persona_admin_enabled: bool = False

    # F4 general mode (non-VIP atencion channel) — env-driven, default off.
    feature_general_mode_enabled: bool = False

    # Quality feedback (Destacar / Reprender). Writes are gated; retrieval
    # always uses quality/vip_id columns (defaults match pre-flag behavior).
    feature_quality_feedback_enabled: bool = False

    # Fase 6 (vínculo Lucien→Diana): expulsiones del Canal VIP avisan a la dueña.
    # FEATURE_LINK_ENABLED on + LINK_CHAT_ID set activates the [LINK] middleware.
    feature_link_enabled: bool = False
    link_chat_id: int | None = None
    link_disable_frozen_until: datetime = datetime(2099, 12, 31, tzinfo=UTC)

    # Evo-Agente Fase 0 (detector de quiebre emocional) — env-driven, default off.
    feature_emotional_detector_enabled: bool = False
    # Retención por tabla (purga): las 3 tablas de agente que crecen sin límite.
    vip_profile_history_ttl_days: int = 90
    turn_category_log_ttl_days: int = 90
    emotional_signal_log_ttl_days: int = 90

    # Evo-Agente Fase 1 (ciclo de resíntesis de memoria) — env-driven, default off.
    feature_profile_synthesis_enabled: bool = False
    # Mensajes del VIP desde la última síntesis que disparan resíntesis (spec 1.1).
    profile_synthesis_volume_threshold: int = 25
    # Minutos sin actividad del VIP tras los cuales el scan marca "cierre de sesión".
    profile_synthesis_inactivity_minutes: int = 30
    # Intervalo del job (scan + síntesis) — scheduling, env-only, sin override system_config.
    profile_synthesis_scan_interval_seconds: int = 900
    # Gates la sobrescritura de stable_traits/sensitivities (spec 1.2). Constante fija,
    # override manual por system_config clave `profile_synthesis`; NUNCA auto-calibrada.
    profile_synthesis_confidence_min: float = 0.6

    # Evo-Agente Fase 2 (autonomía fática, shadow) — env-driven, default off.
    feature_phatic_autonomy: bool = False
    # Confidence mínima del clasificador para considerar un fático "seguro"
    # (modo "no estoy seguro" = confidence < umbral → nunca fast-lane).
    # Constante fija, override manual por system_config clave `phatic_classifier`;
    # NUNCA auto-calibrada.
    classifier_confidence_min: float = 0.7
    # Umbral mínimo de trust por (VIP, categoría) para el carril rápido REAL.
    # RESERVADO para Fase 5 (ítem 4) — este ítem NO lee vip_trust_budget (shadow).
    phatic_trust_min: float = 0.9

    # Pure VIP greeting auto-delivery (plantilla_saludo). Default off.
    # Real delivery kill-switch — NOT shadow. Independent of feature_phatic_autonomy
    # (classifier) and feature_autonomous_mode (full AMS).
    feature_phatic_auto_send: bool = False

    # Evo-Agente Fase 3 (motor de mood, shadow) — env-driven, default off.
    feature_mood_engine: bool = False
    # Promedio móvil con retorno a base:
    # nuevo = actual*(1 - return_rate) + señal*peso*peso_eje + ruido_acotado.
    mood_return_rate: float = 0.05
    mood_signal_weight: float = 0.3
    # Peso por eje (escala la señal del turno por eje). Constantes fijas con
    # override manual por system_config clave `mood_engine`; NUNCA auto-calibradas.
    mood_axis_weights: dict[str, float] = {"playful": 1.0, "warm": 1.0, "energy": 1.0}
    # Ruido acotado ±mood_noise (determinista con semilla en el motor para tests).
    mood_noise: float = 0.05

    # Evo-Agente Fase 5 (presupuesto de confianza, shadow) — env-driven, default off.
    feature_trust_budget: bool = False
    # Mecánica del trust budget por (VIP, categoría). Constantes fijas con override
    # manual por system_config clave `trust_budget`; NUNCA auto-calibradas (incidente).
    trust_budget_initial: float = 0.2      # arranca bajo
    trust_budget_increment: float = 0.05   # sube lento (turno autónomo sin corrección)
    trust_budget_decrement: float = 0.2    # baja rápido (corrección del owner), asimétrico
    trust_budget_threshold: float = 0.9    # umbral autoenvío por categoría (coincide con phatic_trust_min reservado L108)
    trust_dispersion_high: float = 0.25    # 5.2: dispersión del EvaluationProfile que invalida autoenvío
    trust_trend_window_days: int = 14      # ventana "tendencia reciente" de la ficha (EA-06)

    # Fila 4 — Camino a la autonomía (SPEC-AUTONOMIA-CALIBRACION.md). All
    # default off; each phase behind its own flag (regla de oro AGENTS.md §1).
    feature_autonomy_readiness_enabled: bool = False
    # Fase A: C1 motor de coincidencia + comparativas (panel, read-only).
    feature_autonomy_coincidence_enabled: bool = False
    # Fase B: C2 heurística H1 + C3 señal H2 + escritura turn_outcome_log (030).
    feature_autonomy_quality_enabled: bool = False
    # Fase D: C6 puerta de recomendación + botón de activación por VIP.
    feature_autonomy_recommendation_enabled: bool = False
    # C3: ventana de reacción del VIP tras una entrega (horas). Constante fija
    # con override manual por system_config clave `outcome_reaction`; NUNCA
    # auto-calibrada.
    outcome_reaction_window_hours: int = 6
    # C6 puerta (aprobadas por producto, spec §8). Ventana de coincidencia.
    autonomy_window_days: int = 14
    # Umbral de confianza por (VIP, categoría) para recomendar (coincide con
    # trust_budget_threshold; constante espejo del spec).
    autonomy_confidence_min: float = 0.9
    # Tasa de coincidencia mínima para recomendar (spec §8).
    autonomy_match_rate_min: float = 0.95

    # Ops surface (Telegram process edge) — single-instance defaults.
    # health_host is loopback-only (SEC-HEALTH-01); no public bind via env.
    health_host: str = "127.0.0.1"
    health_port: Annotated[int, Field(ge=1, le=65535)] = 8080
    rate_limit_max_events: Annotated[int, Field(ge=1)] = 20
    rate_limit_window_s: Annotated[float, Field(gt=0)] = 10.0
    dedup_ttl_s: Annotated[float, Field(gt=0)] = 300.0

    # VIP history seed via Telethon (personal Diana account session).
    # When api_id + api_hash + session_path are set, adding a VIP imports
    # recent DM history into message_history (skip if chat already has rows).
    telethon_api_id: int | None = None
    telethon_api_hash: SecretStr = SecretStr("")
    telethon_session_path: str = ""  # e.g. /path/to/diana_session (no .session)
    vip_history_seed_limit: Annotated[int, Field(ge=1, le=100)] = 20

    # F5 Pool 2 (REQ-MEM-05/08): backfill pacing + semantic dedup threshold.
    # backfill_interval_sec spaces EVERY processed unit (between VIPs AND
    # between windows of the same VIP) to protect the account from bursts;
    # backfill_dedup_threshold gates the pgvector dedup of extracted facts.
    backfill_interval_sec: Annotated[int, Field(ge=1)] = 3600
    backfill_dedup_threshold: Annotated[float, Field(gt=0, le=1)] = 0.85
    # Fix round (S-F3): recover_stale only reclaims ``processing`` jobs
    # untouched for this long — an overlapping restart never double-extracts
    # a window the previous process is still working on (LLM windows are
    # minutes; 1h covers them with margin and bounds crash-recovery delay).
    backfill_recover_stale_max_age_sec: Annotated[int, Field(ge=1)] = 3600

    @field_validator("health_host", mode="after")
    @classmethod
    def require_loopback_health_host(cls, value: str) -> str:
        """Reject non-loopback binds so /health cannot be exposed publicly."""
        host = value.strip().lower()
        allowed = frozenset({"127.0.0.1", "localhost", "::1"})
        if host not in allowed:
            raise ValueError(
                "health_host must be loopback only "
                "(127.0.0.1, localhost, or ::1)"
            )
        return value.strip()

    @field_validator("telegram_bot_token", "database_url", mode="after")
    @classmethod
    def reject_empty_required_secrets(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def require_asyncpg_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must start with postgresql+asyncpg://")
        return value

    @field_validator("llm_base_url", mode="after")
    @classmethod
    def require_safe_https_llm_base_url(cls, value: str) -> str:
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("llm_base_url must use https scheme")
        host = (parsed.hostname or "").lower()
        if not host:
            raise ValueError("llm_base_url must include a hostname")
        if host in _METADATA_HOSTS:
            raise ValueError("llm_base_url host is not allowed (metadata endpoint)")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError(
                "llm_base_url must not target private or link-local addresses"
            )
        return url.rstrip("/")
