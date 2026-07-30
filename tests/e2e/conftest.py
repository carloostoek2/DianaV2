"""Shared e2e fixtures — DB infrastructure (tier2/3) + Decision helpers (tier1/2/3)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.models import Decision, EvaluationProfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# DB infrastructure — shared by tier2 (repo tests) and tier3 (full wiring)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container():
    """Start a pgvector-enabled PostgreSQL container for the test session."""
    from testcontainers.postgres import PostgresContainer

    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        port=5432,
        username="diana_test",
        password="diana_test",
        dbname="diana_test",
        driver=None,  # We use asyncpg, not psycopg2
    )
    postgres.start()
    yield postgres
    postgres.stop()


@pytest.fixture(scope="session")
def database_url(pg_container) -> str:
    """Build asyncpg-compatible connection URL from the container."""
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    return f"postgresql+asyncpg://diana_test:diana_test@{host}:{port}/diana_test"


@pytest.fixture(scope="session")
def alembic_database_url(pg_container) -> str:
    """Asyncpg URL for Alembic (env.py requires async driver)."""
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    return f"postgresql+asyncpg://diana_test:diana_test@{host}:{port}/diana_test"


@pytest.fixture(scope="session")
def alembic_applied(alembic_database_url: str) -> None:
    """Run all Alembic migrations against the test database (once per session)."""
    env = os.environ.copy()
    env["DATABASE_URL"] = alembic_database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.fail(f"Alembic upgrade failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return None


@pytest.fixture(scope="session")
async def engine(database_url: str, alembic_applied: None) -> AsyncEngine:
    """Create async engine for the test database session."""
    eng = create_async_engine(database_url, echo=False, pool_pre_ping=True, pool_size=10)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory with expire_on_commit=False."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    """Transaction-scoped session — rolled back after each test."""
    async with session_factory() as sess:
        async with sess.begin() as tx:
            yield sess
            await tx.rollback()


# ---------------------------------------------------------------------------
# Decision / evaluation helpers — used by all tiers
# ---------------------------------------------------------------------------


OWNER_ID = 999001
VIP_ID = 777001
CHAT_ID = 100


def make_eval(**kw: float) -> EvaluationProfile:
    defaults = {
        "naturalness": 0.9,
        "precision": 0.9,
        "doctrine": 0.9,
        "consistency": 0.9,
        "safety": 0.95,
        "coverage": 0.9,
        "empathy": 0.9,
    }
    defaults.update(kw)
    return EvaluationProfile(**defaults)


@pytest.fixture
def evaluation() -> EvaluationProfile:
    return make_eval()


@pytest.fixture
def approve_decision(evaluation: EvaluationProfile) -> Decision:
    return Decision(
        action="approve", reason="good", evaluation=evaluation,
        draft_text="Hola, como estas?",
    )


@pytest.fixture
def send_decision(evaluation: EvaluationProfile) -> Decision:
    return Decision(
        action="send", reason="autonomous ok", evaluation=evaluation,
        draft_text="auto reply",
    )


@pytest.fixture
def escalate_decision(evaluation: EvaluationProfile) -> Decision:
    return Decision(
        action="escalate", reason="risk alto", evaluation=evaluation,
        draft_text="",
    )


@pytest.fixture
def consult_doctrine_decision(evaluation: EvaluationProfile) -> Decision:
    return Decision(
        action="consult_doctrine", reason="ambiguous", evaluation=evaluation,
        draft_text="tentative reply",
    )


@pytest.fixture
def fake_actuator() -> FakeTelegramActuator:
    return FakeTelegramActuator()


@pytest.fixture
def clock() -> ImmediateClock:
    return ImmediateClock()


@pytest.fixture
def delay_policy() -> FixedDelayPolicy:
    return FixedDelayPolicy()
