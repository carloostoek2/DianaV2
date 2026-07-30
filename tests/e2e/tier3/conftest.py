"""Tier-3 fixtures: full bot wiring with aiogram dispatcher + real DB.

DB infrastructure fixtures are inherited via pytest's conftest cascade
from tests/e2e/conftest.py (parent).
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram import Bot, Dispatcher
from diana.behavior.fake import FixedDelayPolicy
from diana.composition import build_app
from pydantic import SecretStr
from diana.config.settings import Settings
from diana.llm.fake import FakeLLM


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Minimal settings — database_url is a valid placeholder (overridden via engine injection).

    Uses model_construct to bypass pydantic-settings env-var reading so that
    real OS environment variables never leak into the test configuration.
    """
    return Settings.model_construct(
        telegram_bot_token=SecretStr("1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"),
        owner_telegram_id=999001,
        database_url=SecretStr("postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder"),
        deepseek_api_key="",
        global_mode="supervised",
        feature_gray_zone_enabled=False,
        feature_autonomous_mode=False,
        feature_staging_enabled=False,
        feature_sandbox_enabled=False,
        feature_recontact_enabled=False,
        feature_promo_enabled=False,
        feature_calibration_enabled=False,
        feature_advanced_behavior=False,
        feature_memory_enabled=False,
        log_level="WARNING",
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    """FakeLLM with pre-enqueued responses for cognitive pipeline steps."""
    return FakeLLM(
        text_responses=[
            '{"intent":"saludo","topics":["hola"],"emotion":"positiva","urgency":"baja","risk":"bajo","needs_memory":false,"needs_policy":false,"needs_schedule":false,"needs_examples":false,"needs_history":false,"needs_context":false,"needs_persona_facts":false,"needs_voice_patterns":false,"needs_profile":false}',
            "Hola, como estas?",
            '{"naturalness":0.9,"precision":0.9,"doctrine":0.9,"consistency":0.9,"safety":0.95,"coverage":0.9,"empathy":0.9}',
            '{"action":"approve","reason":"ok"}',
        ],
    )


@pytest.fixture
async def app_container(
    test_settings: Settings,
    database_url: str,
    engine,
    session_factory,
    fake_llm: FakeLLM,
    alembic_applied: None,
):
    """Build the full app container with real DB + FakeLLM + test Bot.

    Injects engine and session_factory so settings.database_url is never used.
    """
    bot = Bot(token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890")

    app = build_app(
        test_settings,
        bot=bot,
        llm=fake_llm,
        session_factory=session_factory,
        engine=engine,
        delay_policy=FixedDelayPolicy(),
    )
    yield app
    await bot.session.close()
    await engine.dispose()


@pytest.fixture
def dispatcher(app_container) -> Dispatcher:
    """The fully-wired aiogram Dispatcher."""
    return app_container.dispatcher


@pytest.fixture
def bot(app_container) -> Bot:
    """The test Bot instance."""
    return app_container.bot
