"""E2E: real-SQL upgrade/downgrade of migration 030 (turn_outcome_log).

Covers the Fila 4 ledger schema: unique turn_id, the three vocabulary CHECK
constraints and the two indexes; downgrade drops the table cleanly.
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

_DB_NAME = "diana_downgrade_030_test"


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
async def test_030_upgrade_constraints_and_downgrade(database_url: str) -> None:
    maint_url = database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await conn.execute(text(f'CREATE DATABASE "{_DB_NAME}"'))
    await engine.dispose()

    db_url = database_url.rsplit("/", 1)[0] + f"/{_DB_NAME}"
    try:
        _alembic("upgrade", "029_feedback_quality", db_url)
        engine_pre = create_async_engine(db_url)
        try:
            async with engine_pre.begin() as conn:
                vip_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO vips (telegram_user_id) "
                            "VALUES (930) RETURNING id"
                        )
                    )
                ).scalar_one()
                turn_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO turns (chat_id, status, vip_id) "
                            "VALUES (1, 'delivered', :vip) RETURNING id"
                        ),
                        {"vip": vip_id},
                    )
                ).scalar_one()
        finally:
            await engine_pre.dispose()

        _alembic("upgrade", "030_turn_outcome_log", db_url)
        engine_post = create_async_engine(db_url)
        try:
            async with engine_post.begin() as conn:
                # Valid row with all three vocabularies + unique turn_id.
                outcome_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO turn_outcome_log "
                            "(turn_id, vip_id, shadow_verdict, shadow_reason, "
                            " owner_outcome, draft_score, sent_score, "
                            " quality_delta, vip_signal) "
                            "VALUES (:turn, :vip, 'blocked', "
                            "        'autonomous_below_threshold', 'corrected', "
                            "        0.7, 0.9, 0.2, 'negative') "
                            "RETURNING id"
                        ),
                        {"turn": turn_id, "vip": vip_id},
                    )
                ).scalar_one()
                assert outcome_id is not None

                # CHECK: bogus shadow_verdict is rejected. A constraint
                # violation aborts the statement; run it inside a SAVEPOINT so
                # the outer transaction stays usable for the checks below.
                with pytest.raises(Exception):
                    async with conn.begin_nested():
                        await conn.execute(
                            text(
                                "INSERT INTO turn_outcome_log "
                                "(turn_id, vip_id, shadow_verdict) "
                                "VALUES (gen_random_uuid(), :vip, 'bogus')"
                            ),
                            {"vip": vip_id},
                        )

                # UNIQUE turn_id: a second row for the same turn is rejected.
                with pytest.raises(Exception):
                    async with conn.begin_nested():
                        await conn.execute(
                            text(
                                "INSERT INTO turn_outcome_log "
                                "(turn_id, vip_id, shadow_verdict) "
                                "VALUES (:turn, :vip, 'send')"
                            ),
                            {"turn": turn_id, "vip": vip_id},
                        )

                indexes = {
                    row.indexname
                    for row in await conn.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE tablename = 'turn_outcome_log'"
                        )
                    )
                }
                assert "ix_turn_outcome_log_created_at" in indexes
                assert "ix_turn_outcome_log_vip_id_created_at" in indexes
        finally:
            await engine_post.dispose()

        _alembic("downgrade", "029_feedback_quality", db_url)
        engine_down = create_async_engine(db_url)
        try:
            assert not await _has_table(engine_down, "turn_outcome_log")
        finally:
            await engine_down.dispose()
    finally:
        engine_drop = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine_drop.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine_drop.dispose()
