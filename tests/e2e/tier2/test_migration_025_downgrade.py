"""E2E: real-SQL downgrade of migration 025 against a fresh Postgres DB.

Covers the Fase 1 synthesis index ``ix_turns_vip_id_created_at`` on
``turns(vip_id, created_at)``: the upgrade creates it, a ``turns`` insert with
``vip_id`` still works (the index does not interfere), and the downgrade
drops the index while leaving ``turns`` intact.

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

_DB_NAME = "diana_downgrade_025_test"
_INDEX_NAME = "ix_turns_vip_id_created_at"


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


async def _index_columns(engine, index: str) -> list[str]:
    """Column list of ``index`` from pg_indexes, or [] if absent."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = :i"
                ),
                {"i": index},
            )
        ).first()
    if row is None:
        return []
    # indexdef ends with:  ON public.turns USING btree (vip_id, created_at)
    defn = row[0]
    start = defn.find("(")
    end = defn.rfind(")")
    cols = defn[start + 1 : end].replace(" ", "").split(",")
    return cols


@pytest.mark.db
@pytest.mark.asyncio
async def test_025_downgrade_reverses_index_and_preserves_turns(
    database_url: str,
) -> None:
    maint_url = database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await conn.execute(text(f'CREATE DATABASE "{_DB_NAME}"'))
    await engine.dispose()

    db_url = database_url.rsplit("/", 1)[0] + f"/{_DB_NAME}"
    try:
        # Upgrade to 025 (index created on top of 024).
        _alembic("upgrade", "025_agent_evolution_synthesis_index", db_url)

        engine2 = create_async_engine(db_url)
        try:
            async with engine2.begin() as conn:
                vip_a = (
                    await conn.execute(
                        text(
                            "INSERT INTO vips (telegram_user_id) "
                            "VALUES (902) RETURNING id"
                        )
                    )
                ).scalar_one()
                # Pre-downgrade asserts: the index exists on (vip_id, created_at).
                assert await _index_columns(engine2, _INDEX_NAME) == [
                    "vip_id",
                    "created_at",
                ]

                # A normal turn insert with vip_id still works with the index.
                turn_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO turns (chat_id, status, vip_id, channel_type) "
                            "VALUES (902, 'received', :vip, 'vip') RETURNING id"
                        ),
                        {"vip": vip_a},
                    )
                ).scalar_one()

                # Querying by vip_id exercises the new index path without error.
                rows = (
                    await conn.execute(
                        text(
                            "SELECT id FROM turns WHERE vip_id = :vip "
                            "AND created_at IS NOT NULL"
                        ),
                        {"vip": vip_a},
                    )
                ).all()
                assert [r[0] for r in rows] == [turn_id]
        finally:
            await engine2.dispose()

        # Downgrade drops the index; turns stays intact.
        _alembic("downgrade", "024_agent_evolution_foundations", db_url)

        engine3 = create_async_engine(db_url)
        try:
            assert await _index_columns(engine3, _INDEX_NAME) == []
            async with engine3.begin() as conn:
                turns_count = (
                    await conn.execute(text("SELECT count(*) FROM turns"))
                ).scalar_one()
                vips_count = (
                    await conn.execute(text("SELECT count(*) FROM vips"))
                ).scalar_one()
            assert turns_count == 1  # the 902 turn survives the downgrade
            assert vips_count == 1  # the 902 VIP survives the downgrade
        finally:
            await engine3.dispose()
    finally:
        engine4 = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine4.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine4.dispose()
