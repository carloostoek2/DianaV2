"""E2E: real-SQL downgrade of migration 020 against a fresh Postgres DB.

Covers the F4 supervised-delivery schema delta: nullable
``gray_zone_queries.business_connection_id``. The downgrade must drop the
column while preserving the rows written at 020.

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

_DB_NAME = "diana_downgrade_020_test"


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


async def _has_column(engine, table: str, column: str) -> bool:
    async with engine.begin() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            )
        ).scalar_one()
    return bool(count)


@pytest.mark.db
@pytest.mark.asyncio
async def test_020_downgrade_reverses_schema_and_preserves_rows(
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
        # 2. Upgrade to 020 (gray_zone_queries.business_connection_id).
        _alembic("upgrade", "020_gray_zone_bc", db_url)

        # 3. Write a VIP turn + gray zone query with business_connection_id.
        engine2 = create_async_engine(db_url)
        async with engine2.begin() as conn:
            turn_id = (
                await conn.execute(
                    text(
                        "INSERT INTO turns (chat_id, status, channel_type) "
                        "VALUES (900, 'received', 'vip') RETURNING id"
                    )
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO gray_zone_queries "
                    "(vip_id, turn_id, question, draft, status, "
                    " business_connection_id) "
                    "VALUES (NULL, :t, 'q', 'd', 'open', 'bc-020')"
                ),
                {"t": turn_id},
            )
            # A NULL business_connection_id row must round-trip too (legacy).
            turn2_id = (
                await conn.execute(
                    text(
                        "INSERT INTO turns (chat_id, status, channel_type) "
                        "VALUES (901, 'received', 'vip') RETURNING id"
                    )
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO gray_zone_queries "
                    "(vip_id, turn_id, question, draft, status, "
                    " business_connection_id) "
                    "VALUES (NULL, :t, 'q', 'd', 'open', NULL)"
                ),
                {"t": turn2_id},
            )
        await engine2.dispose()

        # 4. Downgrade must drop the column.
        _alembic("downgrade", "019_turn_trace_channel_type", db_url)

        # 5. Assert schema delta reversed + rows preserved.
        engine3 = create_async_engine(db_url)
        try:
            assert not await _has_column(
                engine3, "gray_zone_queries", "business_connection_id"
            )
            async with engine3.begin() as conn:
                queries_rows = (
                    await conn.execute(
                        text("SELECT count(*) FROM gray_zone_queries")
                    )
                ).scalar_one()
                assert queries_rows == 2  # both rows survive the downgrade
        finally:
            await engine3.dispose()
    finally:
        engine4 = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine4.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine4.dispose()
