"""E2E: real-SQL downgrade of migration 022 against a fresh Postgres DB.

Covers the F5 memory schema: ``memories.status`` (NOT NULL, server default
``'auto'``) and ``memories.source_turn_id`` (nullable soft reference) plus the
``ix_memories_vip_id_status`` index. The downgrade must reverse both columns
and the index while preserving the rows written at 022.

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

_DB_NAME = "diana_downgrade_022_test"

_EMBEDDING_384 = "[" + ",".join(["0.1"] * 384) + "]"


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
async def test_022_downgrade_reverses_schema_and_preserves_rows(
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
        # 2. Upgrade to 022 (memories.status + source_turn_id + index).
        _alembic("upgrade", "022_memory_status_source_turn", db_url)

        # 3. Write a VIP + two memories rows: one explicit pending_owner with
        #    source_turn_id, one without status (must take the 'auto' default).
        engine2 = create_async_engine(db_url)
        try:
            async with engine2.begin() as conn:
                vip_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO vips (telegram_user_id) "
                            "VALUES (900) RETURNING id"
                        )
                    )
                ).scalar_one()
                await conn.execute(
                    text(
                        "INSERT INTO memories "
                        "(vip_id, embedding, content, category, confidence, "
                        " status, source_turn_id) "
                        "VALUES (:vip, CAST(:emb AS vector), CAST(:content AS jsonb), "
                        "        'sensible', 0.9, 'pending_owner', "
                        "        '00000000-0000-0000-0000-000000000001')"
                    ),
                    {
                        "vip": vip_id,
                        "emb": _EMBEDDING_384,
                        "content": '{"texto":"x","fact":"x"}',
                    },
                )
                await conn.execute(
                    text(
                        "INSERT INTO memories "
                        "(vip_id, embedding, content, category, confidence) "
                        "VALUES (:vip, CAST(:emb AS vector), CAST(:content AS jsonb), "
                        "        'identidad', 0.8)"
                    ),
                    {
                        "vip": vip_id,
                        "emb": _EMBEDDING_384,
                        "content": '{"texto":"x","fact":"x"}',
                    },
                )

                # 4. Pre-downgrade asserts: default applied + index exists.
                default_status = (
                    await conn.execute(
                        text(
                            "SELECT status FROM memories "
                            "WHERE category = 'identidad'"
                        )
                    )
                ).scalar_one()
                assert default_status == "auto"

                has_index = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_indexes "
                            "WHERE indexname = 'ix_memories_vip_id_status'"
                        )
                    )
                ).scalar_one()
                assert has_index == 1

                # Fix round (L3): the status CHECK constraint exists and
                # rejects out-of-domain values at the schema level.
                has_check = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_constraint "
                            "WHERE conname = 'ck_memories_status'"
                        )
                    )
                ).scalar_one()
                assert has_check == 1

            # The failed INSERT aborts its transaction — run it in its own
            # block so the rest of the assertions are not poisoned.
            with pytest.raises(IntegrityError):
                async with engine2.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO memories "
                            "(vip_id, embedding, content, category, confidence, "
                            " status) "
                            "VALUES (:vip, CAST(:emb AS vector), "
                            "        CAST(:content AS jsonb), 'identidad', 0.8, "
                            "        'bogus_status')"
                        ),
                        {
                            "vip": vip_id,
                            "emb": _EMBEDDING_384,
                            "content": '{"texto":"x","fact":"x"}',
                        },
                    )
        finally:
            await engine2.dispose()

        # 5. Downgrade must reverse both columns and the index.
        _alembic("downgrade", "021_atencion_cycles", db_url)

        # 6. Assert schema deltas reversed + rows preserved.
        engine3 = create_async_engine(db_url)
        try:
            async with engine3.begin() as conn:
                has_index = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_indexes "
                            "WHERE indexname = 'ix_memories_vip_id_status'"
                        )
                    )
                ).scalar_one()
                assert has_index == 0

                has_check = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_constraint "
                            "WHERE conname = 'ck_memories_status'"
                        )
                    )
                ).scalar_one()
                assert has_check == 0  # CHECK dropped with the columns

                memories_rows = (
                    await conn.execute(text("SELECT count(*) FROM memories"))
                ).scalar_one()
                assert memories_rows == 2  # both rows survive the downgrade

            assert not await _has_column(engine3, "memories", "status")
            assert not await _has_column(engine3, "memories", "source_turn_id")
        finally:
            await engine3.dispose()
    finally:
        engine4 = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine4.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine4.dispose()
