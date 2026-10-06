"""Shared e2e fixtures — DB infrastructure (tier2/3) + Decision helpers (tier1/2/3)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
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
# Copia de la base real (opcional) — ver audit/ENTORNO.md y
# scripts/refresh_e2e_copy.sh
#
# La suite completa crea y borra tablas (migraciones) y hace DELETE sin filtro,
# así que NO puede correr contra la base real. En su lugar corre contra una copia
# local: `scripts/refresh_e2e_copy.sh` la genera desde la base real (conexión del
# .env, solo lectura) y aquí se restaura en el contenedor desechable de la sesión.
# Sin copia, el contenedor arranca vacío y Alembic aplica las migraciones.
# ---------------------------------------------------------------------------

COPY_DUMP_ENV = "DIANA_E2E_COPY_DUMP"
COPY_OFF_ENV = "DIANA_E2E_COPY_OFF"
DEFAULT_COPY_DUMP = PROJECT_ROOT / "runtime" / "e2e_copy" / "diana_copy.sql"
DB_USER = "diana_test"
DB_PASSWORD = "diana_test"
DB_NAME = "diana_test"


def copy_dump_path() -> Path | None:
    """Path of the real-DB copy to restore, or None when the copy is not in use."""
    if os.environ.get(COPY_OFF_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    raw = os.environ.get(COPY_DUMP_ENV, "").strip()
    path = Path(raw) if raw else DEFAULT_COPY_DUMP
    return path if path.is_file() else None


def _restore_copy(postgres, dump: Path) -> None:
    """Load the real-DB copy into the freshly started container.

    Fails the session loudly if the copy cannot be restored: silently falling
    back to an empty database would turn "the copy broke" into dozens of
    mysterious test failures.
    """
    host = postgres.get_container_host_ip()
    port = postgres.get_exposed_port(5432)
    cmd = [
        "psql",
        "--no-psqlrc",
        "-q",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-f",
        str(dump),
    ]
    env = {**os.environ, "PGPASSWORD": DB_PASSWORD}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    except FileNotFoundError:
        pytest.skip(
            "Hay una copia de la base real pero falta el cliente 'psql' para "
            f"restaurarla ({dump}). Instalá postgresql-client o corré con "
            f"{COPY_OFF_ENV}=1 para usar un contenedor vacío."
        )
    if result.returncode != 0:
        pytest.fail(
            f"No se pudo restaurar la copia de la base real ({dump}).\n"
            f"STDOUT:\n{result.stdout[-4000:]}\nSTDERR:\n{result.stderr[-4000:]}\n"
            "Regenerala con ./scripts/refresh_e2e_copy.sh"
        )


def _container_url(postgres) -> str:
    """Asyncpg connection URL for the session container."""
    host = postgres.get_container_host_ip()
    port = postgres.get_exposed_port(5432)
    return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{host}:{port}/{DB_NAME}"


def pytest_report_header(config) -> str:
    """Make the DB mode visible in the run header — never a silent difference."""
    dump = copy_dump_path()
    if dump is None:
        return (
            "e2e DB: contenedor vacío + migraciones Alembic "
            "(sin copia de la base real; corré ./scripts/refresh_e2e_copy.sh)"
        )
    stat = dump.stat()
    size_mb = stat.st_size / (1024 * 1024)
    generated = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"e2e DB: copia de la base real ({dump.name}, {size_mb:.1f} MB, "
        f"generada {generated}) restaurada en el contenedor"
    )


# ---------------------------------------------------------------------------
# DB infrastructure — shared by tier2 (repo tests) and tier3 (full wiring)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container():
    """Start a pgvector-enabled PostgreSQL container for the test session.

    If a copy of the real database exists (see scripts/refresh_e2e_copy.sh) it is
    restored into the container, so the suite runs against real data without ever
    touching the real database.
    """
    from testcontainers.postgres import PostgresContainer

    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        port=5432,
        username=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
        driver=None,  # We use asyncpg, not psycopg2
    )
    postgres.start()
    dump = copy_dump_path()
    if dump is not None:
        _restore_copy(postgres, dump)
    yield postgres
    postgres.stop()


@pytest.fixture(scope="session")
def database_url(pg_container) -> str:
    """Build asyncpg-compatible connection URL from the container."""
    return _container_url(pg_container)


@pytest.fixture(scope="session")
def alembic_database_url(pg_container) -> str:
    """Asyncpg URL for Alembic (env.py requires async driver)."""
    return _container_url(pg_container)


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
