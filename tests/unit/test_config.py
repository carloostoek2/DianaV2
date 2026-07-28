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
    # Supervised: fixed 2 min; autonomous: 3–8 min (REQ-HUM-04)
    assert settings.delivery_supervised_delay_min == 120.0
    assert settings.delivery_supervised_delay_max == 120.0
    assert settings.delivery_autonomous_delay_min == 180.0
    assert settings.delivery_autonomous_delay_max == 480.0


def test_settings_rejects_non_positive_delay_min(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv("DELIVERY_SUPERVISED_DELAY_MIN", "0")
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


@pytest.mark.parametrize(
    ("env_key", "attr"),
    [
        ("FEATURE_AUTONOMOUS_MODE", "feature_autonomous_mode"),
        ("FEATURE_RECONTACT_ENABLED", "feature_recontact_enabled"),
    ],
)
def test_settings_f3_flag_env_override_true(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    attr: str,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv(env_key, "true")
    settings = Settings()
    assert getattr(settings, attr) is True
    # Sibling F3 flags remain false when only one env is set.
    for other in (
        "feature_autonomous_mode",
        "feature_recontact_enabled",
        "feature_promo_enabled",
        "feature_calibration_enabled",
        "feature_advanced_behavior",
    ):
        if other != attr:
            assert getattr(settings, other) is False


def test_random_delay_policy_rejects_invalid_ranges() -> None:
    from diana.composition import RandomDelayPolicy

    with pytest.raises(ValueError):
        RandomDelayPolicy(supervised_min=0.0, supervised_max=120.0)
    with pytest.raises(ValueError):
        RandomDelayPolicy(autonomous_min=-1.0, autonomous_max=480.0)
    with pytest.raises(ValueError):
        RandomDelayPolicy(supervised_min=200.0, supervised_max=100.0)
    with pytest.raises(ValueError):
        RandomDelayPolicy(autonomous_min=500.0, autonomous_max=100.0)


def test_random_delay_policy_mode_ranges() -> None:
    from diana.composition import RandomDelayPolicy

    policy = RandomDelayPolicy(
        supervised_min=120.0,
        supervised_max=120.0,
        autonomous_min=180.0,
        autonomous_max=480.0,
        rng=__import__("random").Random(0),
    )
    assert policy.initial_delay_seconds("supervised") == 120.0
    assert policy.initial_delay_seconds("fake_delivery") == 120.0
    auto = policy.initial_delay_seconds("autonomous")
    assert 180.0 <= auto <= 480.0


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


def test_settings_ops_surface_defaults(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health bind + rate-limit + dedup TTL defaults (ops-surface hardener)."""
    from diana.config import Settings

    _set_required_env(monkeypatch)
    settings = Settings()
    assert settings.health_host == "127.0.0.1"
    assert settings.health_port == 8080
    assert settings.rate_limit_max_events == 20
    assert settings.rate_limit_window_s == 10.0
    assert settings.dedup_ttl_s == 300.0


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "LocalHost"])
def test_settings_accepts_loopback_health_hosts(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    """SEC-HEALTH-01: loopback hosts only."""
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv("HEALTH_HOST", host)
    settings = Settings()
    assert settings.health_host.lower() in {"127.0.0.1", "localhost", "::1"}


@pytest.mark.parametrize("host", ["0.0.0.0", "1.2.3.4", "*", "example.com"])
def test_settings_rejects_non_loopback_health_host(
    clear_settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    from diana.config import Settings

    _set_required_env(monkeypatch)
    monkeypatch.setenv("HEALTH_HOST", host)
    with pytest.raises(ValidationError):
        Settings()

