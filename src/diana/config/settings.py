"""Env-driven application settings. Secrets never live in the repository."""

from __future__ import annotations

import ipaddress
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
    feature_gray_zone_enabled: bool = False
    feature_staging_enabled: bool = False
    feature_sandbox_enabled: bool = False

    # F3 feature flag static defaults (runtime DB merge is a later item).
    feature_autonomous_mode: bool = False
    feature_recontact_enabled: bool = False
    feature_promo_enabled: bool = False
    feature_calibration_enabled: bool = False
    feature_advanced_behavior: bool = False

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
