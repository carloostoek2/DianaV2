"""Unit tests for env-driven Settings (AC-07)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "999001")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://diana:diana@localhost:5432/diana",
    )


def test_settings_constructs_from_valid_env(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    settings = Settings()
    assert settings.telegram_bot_token.get_secret_value() == "test-token-not-real"
    assert settings.owner_telegram_id == 999001
    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")


def test_settings_repr_does_not_leak_token(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    settings = Settings()
    rendered = repr(settings)
    assert "test-token-not-real" not in rendered
    dumped = settings.model_dump()
    # SecretStr serializes to SecretStr object or redacted form, not raw string in dump by default
    assert dumped["telegram_bot_token"].get_secret_value() == "test-token-not-real"
    assert "test-token-not-real" not in str(dumped["telegram_bot_token"])


def test_settings_missing_required_field_raises(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    # OWNER_TELEGRAM_ID and DATABASE_URL intentionally omitted
    with pytest.raises(ValidationError):
        Settings()


def test_settings_defaults_supervised_and_ttl(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    settings = Settings()
    assert settings.global_mode == "supervised"
    assert settings.trace_ttl_days == 30
    assert settings.log_level == "INFO"
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.deepseek_api_key.get_secret_value() == ""


def test_settings_has_no_hardcoded_bot_token_default(
    clear_settings_env: None,
) -> None:
    from pydantic_core import PydanticUndefined

    from diana.config import Settings

    field = Settings.model_fields["telegram_bot_token"]
    assert field.is_required() is True
    assert field.default is PydanticUndefined
    assert field.default_factory is None


@pytest.mark.parametrize(
    "field_name",
    ["telegram_bot_token", "owner_telegram_id", "database_url"],
)
def test_settings_required_secrets_have_no_defaults(
    clear_settings_env: None,
    field_name: str,
) -> None:
    """AC-07 / L3: required secrets must not ship unsafe production defaults."""
    from pydantic_core import PydanticUndefined

    from diana.config import Settings

    field = Settings.model_fields[field_name]
    assert field.is_required() is True
    assert field.default is PydanticUndefined
    assert field.default_factory is None


@pytest.mark.parametrize(
    "missing_key",
    ["TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID", "DATABASE_URL"],
)
def test_settings_each_required_env_missing_raises(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.delenv(missing_key, raising=False)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("env_key", "empty_value"),
    [
        ("TELEGRAM_BOT_TOKEN", ""),
        ("TELEGRAM_BOT_TOKEN", "   "),
        ("DATABASE_URL", ""),
    ],
)
def test_settings_rejects_empty_required_secrets(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    empty_value: str,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv(env_key, empty_value)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_non_asyncpg_database_url(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://diana:diana@localhost:5432/diana")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://api.deepseek.com",
        "file:///tmp/x",
        "https://169.254.169.254/latest/meta-data",
        "https://127.0.0.1/v1",
        "https://10.0.0.8/",
    ],
)
def test_settings_rejects_unsafe_llm_base_url(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
    bad_url: str,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", bad_url)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_accepts_delivery_modes(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import get_args

    from diana.config import Settings

    _set_required_env(monkeypatch)
    for mode in ("supervised", "autonomous", "fake_delivery"):
        monkeypatch.setenv("GLOBAL_MODE", mode)
        settings = Settings()
        assert settings.global_mode == mode

    args = get_args(Settings.model_fields["global_mode"].annotation)
    assert set(args) == {"supervised", "autonomous", "fake_delivery"}


def test_settings_rejects_invalid_global_mode(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv("GLOBAL_MODE", "nope")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_delivery_retry_and_delay_defaults(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    settings = Settings()
    assert settings.delivery_max_send_attempts == 3
    assert settings.delivery_retry_backoff_seconds == 0.05
    assert settings.delivery_initial_delay_min == 4.0
    assert settings.delivery_initial_delay_max == 14.0


def test_settings_rejects_non_positive_delay_min(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv("DELIVERY_INITIAL_DELAY_MIN", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_feature_flag_defaults_are_false(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2 + F3: all 9 feature flags default to False."""
    from diana.config import Settings

    _set_required_env(monkeypatch)
    settings = Settings()
    # F2
    assert settings.feature_memory_enabled is False
    assert settings.feature_gray_zone_enabled is False
    assert settings.feature_staging_enabled is False
    assert settings.feature_sandbox_enabled is False
    # F3
    assert settings.feature_autonomous_mode is False
    assert settings.feature_recontact_enabled is False
    assert settings.feature_promo_enabled is False
    assert settings.feature_calibration_enabled is False
    assert settings.feature_advanced_behavior is False


def test_settings_feature_autonomous_mode_env_override_true(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv("FEATURE_AUTONOMOUS_MODE", "true")
    settings = Settings()
    assert settings.feature_autonomous_mode is True
    assert settings.feature_recontact_enabled is False
    assert settings.feature_promo_enabled is False
    assert settings.feature_calibration_enabled is False
    assert settings.feature_advanced_behavior is False


def test_random_delay_policy_rejects_zero_initial_min() -> None:
    from diana.composition import RandomDelayPolicy

    with pytest.raises(ValueError):
        RandomDelayPolicy(initial_min=0.0, initial_max=14.0)
    with pytest.raises(ValueError):
        RandomDelayPolicy(initial_min=-1.0, initial_max=14.0)
    with pytest.raises(ValueError):
        RandomDelayPolicy(initial_min=10.0, initial_max=5.0)
    policy = RandomDelayPolicy(initial_min=4.0, initial_max=14.0)
    assert 4.0 <= policy.initial_delay_seconds() <= 14.0


@pytest.mark.parametrize(
    ("env_key", "bad_value"),
    [
        ("OWNER_TELEGRAM_ID", "0"),
        ("OWNER_TELEGRAM_ID", "-1"),
        ("TRACE_TTL_DAYS", "0"),
        ("TRACE_TTL_DAYS", "-5"),
        ("LOG_LEVEL", "NOT_A_LEVEL"),
    ],
)
def test_settings_rejects_invalid_numeric_and_log_level(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    bad_value: str,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv(env_key, bad_value)
    with pytest.raises(ValidationError):
        Settings()
