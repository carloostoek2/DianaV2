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
    delivery_initial_delay_min: Annotated[float, Field(gt=0)] = 4.0
    delivery_initial_delay_max: Annotated[float, Field(gt=0)] = 14.0
    trace_ttl_days: Annotated[int, Field(ge=1)] = 30
    log_level: LogLevel = "INFO"

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
