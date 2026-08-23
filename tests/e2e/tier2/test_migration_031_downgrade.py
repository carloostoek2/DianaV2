"""E2E: real-SQL upgrade/downgrade of migration 031 (profile_synthesis_queue).

Covers the durable synthesis queue: trigger/status CHECKs, PK on vip_id and a
clean downgrade.
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

_DB_NAME = "diana_downgrade_031_test"


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


async def _has_table(engine, name: str) -> bool:
    async with engine.begin() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name = :t AND table_schema = 'public'"
                ),
                {"t": name},
            )
        ).scalar_one()
    return bool(count)


@pytest.mark.db
@pytest.mark.asyncio
async def test_031_upgrade_checks_and_downgrade(database_url: str) -> None:
    maint_url = database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await conn.execute(text(f'CREATE DATABASE "{_DB_NAME}"'))
    await engine.dispose()

    db_url = database_url.rsplit("/", 1)[0] + f"/{_DB_NAME}"
    try:
        _alembic("upgrade", "030_turn_outcome_log", db_url)
        engine_pre = create_async_engine(db_url)
        try:
            async with engine_pre.begin() as conn:
                vip_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO vips (telegram_user_id) "
                            "VALUES (931) RETURNING id"
                        )
                    )
                ).scalar_one()
        finally:
            await engine_pre.dispose()

        _alembic("upgrade", "031_profile_synthesis_queue", db_url)
        engine_post = create_async_engine(db_url)
        try:
            async with engine_post.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO profile_synthesis_queue "
                        "(vip_id, trigger) VALUES (:vip, 'volume')"
                    ),
                    {"vip": vip_id},
                )
                # PK: same VIP again → upsert conflict without ON CONFLICT.
                with pytest.raises(Exception):
                    await conn.execute(
                        text(
                            "INSERT INTO profile_synthesis_queue "
                            "(vip_id, trigger) VALUES (:vip, 'session_close')"
                        ),
                        {"vip": vip_id},
                    )
                # CHECK: bogus trigger rejected.
                with pytest.raises(Exception):
                    await conn.execute(
                        text(
                            "INSERT INTO profile_synthesis_queue "
                            "(vip_id, trigger) VALUES "
                            "(gen_random_uuid(), 'bogus')"
                        )
                    )
        finally:
            await engine_post.dispose()

        _alembic("downgrade", "030_turn_outcome_log", db_url)
        engine_down = create_async_engine(db_url)
        try:
            assert not await _has_table(engine_down, "profile_synthesis_queue")
        finally:
            await engine_down.dispose()
    finally:
        engine_drop = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine_drop.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine_drop.dispose()
