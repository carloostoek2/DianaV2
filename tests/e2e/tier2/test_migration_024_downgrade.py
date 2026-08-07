"""E2E: real-SQL downgrade of migration 024 against a fresh Postgres DB.

Covers the evo-agente Fase 0 foundations: the six new tables
(``vip_profile``, ``vip_profile_history``, ``vip_mood_state``,
``vip_trust_budget``, ``turn_category_log``, ``emotional_signal_log``) with
their Text + CHECK vocabularies and indexes. The downgrade must drop the six
tables while preserving the ``vips`` rows.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_DB_NAME = "diana_downgrade_024_test"

_TABLES = (
    "vip_profile",
    "vip_profile_history",
    "vip_mood_state",
    "vip_trust_budget",
    "turn_category_log",
    "emotional_signal_log",
)

_CHECKS = (
    "ck_vip_profile_synthesis_trigger",
    "ck_vip_trust_budget_turn_category",
    "ck_turn_category_log_category",
    "ck_emotional_signal_log_signal_type",
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


async def _has_table(engine, table: str) -> bool:
    async with engine.begin() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name = :t"
                ),
                {"t": table},
            )
        ).scalar_one()
    return bool(count)


@pytest.mark.db
@pytest.mark.asyncio
async def test_024_downgrade_reverses_schema_and_preserves_vips(
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
        # 2. Upgrade to 024 (six tables + CHECKs + indexes).
        _alembic("upgrade", "024_agent_evolution_foundations", db_url)

        engine2 = create_async_engine(db_url)
        try:
            async with engine2.begin() as conn:
                vip_a = (
                    await conn.execute(
                        text(
                            "INSERT INTO vips (telegram_user_id) "
                            "VALUES (901) RETURNING id"
                        )
                    )
                ).scalar_one()

                # 3. Pre-downgrade asserts: six tables exist.
                for table in _TABLES:
                    assert await _has_table(engine2, table), table

                # All four CHECK constraints exist.
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

                # Composite PK on vip_trust_budget.
                pk_columns = (
                    await conn.execute(
                        text(
                            "SELECT array_agg(column_name ORDER BY column_name) "
                            "FROM information_schema.key_column_usage "
                            "WHERE table_name = 'vip_trust_budget' "
                            "AND constraint_name = 'vip_trust_budget_pkey'"
                        )
                    )
                ).scalar_one()
                assert set(pk_columns) == {"vip_id", "turn_category"}

                # Valid insert into emotional_signal_log referencing the turn
                # requires a turns row — create one to prove FK wiring works.
                turn_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO turns (chat_id, status) "
                            "VALUES (901, 'received') RETURNING id"
                        )
                    )
                ).scalar_one()
                await conn.execute(
                    text(
                        "INSERT INTO emotional_signal_log "
                        "(vip_id, turn_id, signal_type, intensity, "
                        " should_trigger_synthesis, should_escalate_to_owner) "
                        "VALUES (:vip, :turn, 'angustia', 0.85, true, true)"
                    ),
                    {"vip": vip_a, "turn": turn_id},
                )

            # CHECK constraint rejects out-of-domain signal_type (own transaction).
            with pytest.raises(IntegrityError):
                async with engine2.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO emotional_signal_log "
                            "(vip_id, turn_id, signal_type, intensity) "
                            "VALUES (:vip, :turn, 'bogus', 0.5)"
                        ),
                        {"vip": vip_a, "turn": turn_id},
                    )
        finally:
            await engine2.dispose()

        # 4. Downgrade must drop the six tables.
        _alembic("downgrade", "023_backfill_queue", db_url)

        # 5. Assert schema reversed + vips rows preserved.
        engine3 = create_async_engine(db_url)
        try:
            for table in _TABLES:
                assert not await _has_table(engine3, table), table
            async with engine3.begin() as conn:
                vips_count = (
                    await conn.execute(text("SELECT count(*) FROM vips"))
                ).scalar_one()
                assert vips_count == 1  # the 901 VIP survives the downgrade
        finally:
            await engine3.dispose()
    finally:
        engine4 = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine4.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine4.dispose()
