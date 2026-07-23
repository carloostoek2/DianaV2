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
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    # Avoid accidental load of a developer .env during unit tests.
    monkeypatch.chdir(os.path.dirname(__file__))
    yield
