"""Env-driven application settings. Secrets never live in the repository."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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
    global_mode: Literal["supervised"] = "supervised"
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
