"""E2E: real-SQL downgrade of migration 023 against a fresh Postgres DB.

Covers the F5 Pool 2 backfill queue schema: ``backfill_queue`` table with the
status CHECK constraint, the ``(status, created_at)`` index and the partial
unique index ``uq_backfill_queue_active_vip`` (at most one active job per
VIP). The downgrade must drop the table while preserving the ``vips`` rows.

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

_DB_NAME = "diana_downgrade_023_test"


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
async def test_023_downgrade_reverses_schema_and_preserves_vips(
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
        # 2. Upgrade to 023 (backfill_queue table + CHECK + indexes).
        _alembic("upgrade", "023_backfill_queue", db_url)

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

                # 3. Two rows: one pending, one done with outcome='ok'.
                await conn.execute(
                    text(
                        "INSERT INTO backfill_queue "
                        "(vip_id, chat_id, status, window_index, state, attempts) "
                        "VALUES (:vip, 901, 'pending', 0, CAST(:state AS jsonb), 0)"
                    ),
                    {"vip": vip_a, "state": '{"hechos":[]}'},
                )
                await conn.execute(
                    text(
                        "INSERT INTO backfill_queue "
                        "(vip_id, chat_id, status, window_index, state, attempts, "
                        " outcome) "
                        "VALUES (:vip, 901, 'done', 2, CAST(:state AS jsonb), 1, 'ok')"
                    ),
                    {"vip": vip_a, "state": '{"hechos":[]}'},
                )

                # 4. Pre-downgrade asserts.
                has_uq = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_indexes "
                            "WHERE indexname = 'uq_backfill_queue_active_vip'"
                        )
                    )
                ).scalar_one()
                assert has_uq == 1

                has_ix = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_indexes "
                            "WHERE indexname = 'ix_backfill_queue_status_created'"
                        )
                    )
                ).scalar_one()
                assert has_ix == 1

                has_check = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_constraint "
                            "WHERE conname = 'ck_backfill_queue_status'"
                        )
                    )
                ).scalar_one()
                assert has_check == 1

            # CHECK constraint rejects out-of-domain status (own transaction).
            with pytest.raises(IntegrityError):
                async with engine2.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO backfill_queue "
                            "(vip_id, chat_id, status) "
                            "VALUES (:vip, 901, 'bogus_status')"
                        ),
                        {"vip": vip_a},
                    )

            # Partial unique index: a second active (pending) job for the same
            # VIP fails — the first pending row for VIP A is still there.
            with pytest.raises(IntegrityError):
                async with engine2.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO backfill_queue "
                            "(vip_id, chat_id, status) "
                            "VALUES (:vip, 901, 'pending')"
                        ),
                        {"vip": vip_a},
                    )
        finally:
            await engine2.dispose()

        # 5. Downgrade must drop the whole table.
        _alembic("downgrade", "022_memory_status_source_turn", db_url)

        # 6. Assert schema reversed + vips rows preserved.
        engine3 = create_async_engine(db_url)
        try:
            assert not await _has_table(engine3, "backfill_queue")
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
