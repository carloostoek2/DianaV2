"""Shared pytest fixtures for Diana unit tests."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture
def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove Settings-related env vars so tests control configuration explicitly."""
    keys = [
        "TELEGRAM_BOT_TOKEN",
        "OWNER_TELEGRAM_ID",
        "DATABASE_URL",
        "DEEPSEEK_API_KEY",
        "LLM_BASE_URL",
        "GLOBAL_MODE",
        "TRACE_TTL_DAYS",
        "LOG_LEVEL",
        # F2 feature flags
        "FEATURE_MEMORY_ENABLED",
        "FEATURE_GRAY_ZONE_ENABLED",
        "FEATURE_STAGING_ENABLED",
        "FEATURE_SANDBOX_ENABLED",
        # F3 feature flags
        "FEATURE_AUTONOMOUS_MODE",
        "FEATURE_RECONTACT_ENABLED",
        "FEATURE_PROMO_ENABLED",
        "FEATURE_CALIBRATION_ENABLED",
        "FEATURE_ADVANCED_BEHAVIOR",
        "FEATURE_PERSONA_ADMIN_ENABLED",
        # F4 feature flags
        "FEATURE_GENERAL_MODE_ENABLED",
        # Evo-Agente Fase 0 feature flags
        "FEATURE_EMOTIONAL_DETECTOR_ENABLED",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    # Avoid accidental load of a developer .env during unit tests.
    monkeypatch.chdir(os.path.dirname(__file__))
    yield
