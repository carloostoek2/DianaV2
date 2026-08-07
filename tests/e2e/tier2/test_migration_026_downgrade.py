"""E2E: real-SQL downgrade of migration 026 against a fresh Postgres DB.

Covers the Fase 2 shadow columns added to ``turn_category_log``:
``would_autonomous`` (bool NULL) + ``confidence`` (float NULL). The upgrade
must add the two columns (nullable), a row written with the new columns must
persist, and the downgrade must drop them while preserving the table, its
CHECK constraint and its indexes (columns, NOT tables — the count stays 32).

Runs on a dedicated database so it never disturbs the session-level migrated
DB used by the other tier2 tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_DB_NAME = "diana_downgrade_026_test"

_NEW_COLUMNS = ("would_autonomous", "confidence")

_CHECKS = ("ck_turn_category_log_category",)

_INDEXES = (
    "ix_turn_category_log_chat_id_created_at",
    "ix_turn_category_log_created_at",
)


def _alembic(args: str, target: str, url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", args, target],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, (
        f"alembic {args} {target} failed:\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


async def _column_nullable(engine, column: str) -> str | None:
    async with engine.begin() as conn:
        value = (
            await conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'turn_category_log' AND column_name = :c"
                ),
                {"c": column},
            )
        ).scalar_one_or_none()
    return value


@pytest.mark.db
@pytest.mark.asyncio
async def test_026_downgrade_reverses_shadow_columns_and_preserves_table(
    database_url: str,
) -> None:
    # 1. Dedicated database on the session Postgres server.
    maint_url = database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await conn.execute(text(f'CREATE DATABASE "{_DB_NAME}"'))
    await engine.dispose()

    db_url = database_url.rsplit("/", 1)[0] + f"/{_DB_NAME}"
    try:
        # 2. Upgrade to 026 (adds the two shadow columns).
        _alembic("upgrade", "026_agent_evolution_turn_category_columns", db_url)

        engine2 = create_async_engine(db_url)
        try:
            async with engine2.begin() as conn:
                # 3. The two new columns exist and are nullable.
                for column in _NEW_COLUMNS:
                    assert await _column_nullable(engine2, column) == "YES", column

                vip_a = (
                    await conn.execute(
                        text(
                            "INSERT INTO vips (telegram_user_id) "
                            "VALUES (902) RETURNING id"
                        )
                    )
                ).scalar_one()
                turn_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO turns (chat_id, status) "
                            "VALUES (902, 'received') RETURNING id"
                        )
                    )
                ).scalar_one()

                # A row written with the new columns persists and round-trips.
                await conn.execute(
                    text(
                        "INSERT INTO turn_category_log "
                        "(vip_id, turn_id, chat_id, category, "
                        " would_autonomous, confidence) "
                        "VALUES (:vip, :turn, 902, 'fatico', true, 0.9)"
                    ),
                    {"vip": vip_a, "turn": turn_id},
                )
                row = (
                    await conn.execute(
                        text(
                            "SELECT category, would_autonomous, confidence "
                            "FROM turn_category_log WHERE turn_id = :turn"
                        ),
                        {"turn": turn_id},
                    )
                ).one()
                assert row.category == "fatico"
                assert row.would_autonomous is True
                assert abs(row.confidence - 0.9) < 1e-9

                # CHECK + indexes still present alongside the new columns.
                for check in _CHECKS:
                    count = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM pg_constraint "
                                "WHERE conname = :c"
                            ),
                            {"c": check},
                        )
                    ).scalar_one()
                    assert count == 1, check
                for index in _INDEXES:
                    count = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM pg_indexes "
                                "WHERE indexname = :i"
                            ),
                            {"i": index},
                        )
                    ).scalar_one()
                    assert count == 1, index
        finally:
            await engine2.dispose()

        # 4. Downgrade must drop the two columns (back to migration 025 shape).
        _alembic("downgrade", "025_agent_evolution_synthesis_index", db_url)

        # 5. Assert the columns are gone while the table + CHECK + indexes live.
        engine3 = create_async_engine(db_url)
        try:
            for column in _NEW_COLUMNS:
                assert await _column_nullable(engine3, column) is None, column
            async with engine3.begin() as conn:
                for check in _CHECKS:
                    count = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM pg_constraint "
                                "WHERE conname = :c"
                            ),
                            {"c": check},
                        )
                    ).scalar_one()
                    assert count == 1, check
                for index in _INDEXES:
                    count = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM pg_indexes "
                                "WHERE indexname = :i"
                            ),
                            {"i": index},
                        )
                    ).scalar_one()
                    assert count == 1, index
        finally:
            await engine3.dispose()
    finally:
        engine4 = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine4.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine4.dispose()
