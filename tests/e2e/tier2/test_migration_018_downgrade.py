"""E2E: real-SQL downgrade of migration 018 against a fresh Postgres DB.

Covers B5: the downgrade must succeed even when an owner-saved atencion row
(source='db', active) coexists with an active VIP row — the single-channel
``(is_active) WHERE is_active`` index recreate would otherwise abort on a
duplicate-active violation. Also asserts the schema/seed deltas reverse.

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

_DB_NAME = "diana_downgrade_test"


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


@pytest.mark.db
@pytest.mark.asyncio
async def test_018_downgrade_reverses_with_owner_saved_atencion_row(
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
        # 2. Upgrade to 018 (adds channel_type, multi-channel index, seed).
        _alembic("upgrade", "018_channel_type_atencion", db_url)

        # 3. Simulate a live DB: an active VIP row + an owner-saved active
        #    atencion row (source='db'). The seed is already active at the
        #    seed version (max+1 at migration time).
        engine2 = create_async_engine(db_url)
        async with engine2.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO persona_versions "
                    "(channel_type, version, source, payload, is_active) "
                    "VALUES ('vip', 1, 'db', '{}'::jsonb, true)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO persona_versions "
                    "(channel_type, version, source, payload, is_active) "
                    "VALUES ('atencion', 3, 'db', '{}'::jsonb, true)"
                )
            )
        await engine2.dispose()

        # 4. Downgrade must NOT abort on the duplicate-active row (B5).
        _alembic("downgrade", "017_persona_versions", db_url)

        # 5. Assert the schema/seed deltas reversed.
        engine3 = create_async_engine(db_url)
        async with engine3.begin() as conn:
            remaining = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM persona_versions "
                        "WHERE channel_type = 'atencion'"
                    )
                )
            ).scalar_one()
            assert remaining == 0

            has_column = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'persona_versions' "
                        "AND column_name = 'channel_type'"
                    )
                )
            ).scalar_one()
            assert has_column == 0

            has_limits = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_name = 'daily_message_limits'"
                    )
                )
            ).scalar_one()
            assert has_limits == 0

            # The recreated single-channel active index holds exactly the
            # active VIP row (no duplicate-active violation).
            active = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM persona_versions WHERE is_active"
                    )
                )
            ).scalar_one()
            assert active == 1
        await engine3.dispose()
    finally:
        engine4 = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine4.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine4.dispose()
