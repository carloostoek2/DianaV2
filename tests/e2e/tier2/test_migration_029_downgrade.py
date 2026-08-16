"""E2E: real-SQL upgrade/downgrade of migration 029 against a fresh Postgres DB.

Covers FB-04 additive columns: ``examples.quality`` (NOT NULL default
``standard``) plus ``examples.vip_id`` / ``policies.vip_id`` (nullable FK to
``vips.id``, no ON DELETE). Pre-029 rows must backfill to standard + NULL
vip_id; downgrade must drop the new objects without deleting rows.
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

_DB_NAME = "diana_downgrade_029_test"
_EMBEDDING_384 = "[" + ",".join(["0.1"] * 384) + "]"
_HNSW = ("examples_embedding_idx", "policies_embedding_idx")
_NEW_INDEXES = ("ix_examples_vip_id", "ix_policies_vip_id")
_NEW_FKS = ("fk_examples_vip_id", "fk_policies_vip_id")


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


async def _column_meta(engine, table: str, column: str) -> tuple[str | None, str | None]:
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            )
        ).one_or_none()
    if row is None:
        return None, None
    return row.is_nullable, row.column_default


async def _index_count(conn, name: str) -> int:
    return (
        await conn.execute(
            text("SELECT count(*) FROM pg_indexes WHERE indexname = :i"),
            {"i": name},
        )
    ).scalar_one()


async def _constraint_count(conn, name: str) -> int:
    return (
        await conn.execute(
            text("SELECT count(*) FROM pg_constraint WHERE conname = :c"),
            {"c": name},
        )
    ).scalar_one()


@pytest.mark.db
@pytest.mark.asyncio
async def test_029_upgrade_defaults_fk_and_downgrade_preserves_rows(
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
        _alembic("upgrade", "028_link_events", db_url)

        engine_pre = create_async_engine(db_url)
        try:
            async with engine_pre.begin() as conn:
                vip_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO vips (telegram_user_id) "
                            "VALUES (929) RETURNING id"
                        )
                    )
                ).scalar_one()
                example_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO examples "
                            "(embedding, turn_text, draft_text, "
                            " corrected_text, context) "
                            "VALUES (CAST(:emb AS vector), 'pre', 'draft', "
                            "        'corr', CAST(:ctx AS jsonb)) "
                            "RETURNING id"
                        ),
                        {"emb": _EMBEDDING_384, "ctx": "{}"},
                    )
                ).scalar_one()
                policy_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO policies "
                            "(embedding, trigger_description, rule) "
                            "VALUES (CAST(:emb AS vector), "
                            "        'pre trigger', 'pre rule') "
                            "RETURNING id"
                        ),
                        {"emb": _EMBEDDING_384},
                    )
                ).scalar_one()
        finally:
            await engine_pre.dispose()

        _alembic("upgrade", "029_feedback_quality", db_url)

        engine_post = create_async_engine(db_url)
        try:
            quality_null, quality_default = await _column_meta(
                engine_post, "examples", "quality"
            )
            assert quality_null == "NO"
            assert quality_default is not None and "standard" in quality_default

            examples_vip_null, _ = await _column_meta(
                engine_post, "examples", "vip_id"
            )
            policies_vip_null, _ = await _column_meta(
                engine_post, "policies", "vip_id"
            )
            assert examples_vip_null == "YES"
            assert policies_vip_null == "YES"

            async with engine_post.begin() as conn:
                pre_example = (
                    await conn.execute(
                        text(
                            "SELECT quality, vip_id FROM examples "
                            "WHERE id = :id"
                        ),
                        {"id": example_id},
                    )
                ).one()
                assert pre_example.quality == "standard"
                assert pre_example.vip_id is None

                pre_policy = (
                    await conn.execute(
                        text(
                            "SELECT vip_id, scope FROM policies WHERE id = :id"
                        ),
                        {"id": policy_id},
                    )
                ).one()
                assert pre_policy.vip_id is None
                assert pre_policy.scope == "all"

                for index in _NEW_INDEXES + _HNSW:
                    assert await _index_count(conn, index) == 1, index

                assert await _constraint_count(conn, "ck_examples_quality") == 0
                for fk_name in _NEW_FKS:
                    assert await _constraint_count(conn, fk_name) == 1, fk_name

                fk_rows = (
                    await conn.execute(
                        text(
                            "SELECT conname, confdeltype FROM pg_constraint "
                            "WHERE conname IN "
                            "('fk_examples_vip_id', 'fk_policies_vip_id')"
                        )
                    )
                ).all()
                assert {row.conname for row in fk_rows} == set(_NEW_FKS)
                for row in fk_rows:
                    deltype = row.confdeltype
                    if isinstance(deltype, bytes):
                        deltype = deltype.decode()
                    assert deltype not in {"c", "n"}
                    assert deltype in {"a", "r"}

                gold_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO examples "
                            "(embedding, turn_text, draft_text, "
                            " corrected_text, context, quality, vip_id) "
                            "VALUES (CAST(:emb AS vector), 'gold', 'd', "
                            "        'c', CAST(:ctx AS jsonb), 'gold', :vip) "
                            "RETURNING id"
                        ),
                        {
                            "emb": _EMBEDDING_384,
                            "ctx": "{}",
                            "vip": vip_id,
                        },
                    )
                ).scalar_one()
                assert gold_id is not None

                default_quality = (
                    await conn.execute(
                        text(
                            "INSERT INTO examples "
                            "(embedding, turn_text, draft_text, "
                            " corrected_text, context) "
                            "VALUES (CAST(:emb AS vector), 'noq', 'd', "
                            "        'c', CAST(:ctx AS jsonb)) "
                            "RETURNING quality"
                        ),
                        {"emb": _EMBEDDING_384, "ctx": "{}"},
                    )
                ).scalar_one()
                assert default_quality == "standard"

                default_vip = (
                    await conn.execute(
                        text(
                            "INSERT INTO examples "
                            "(embedding, turn_text, draft_text, "
                            " corrected_text, context) "
                            "VALUES (CAST(:emb AS vector), 'novip', 'd', "
                            "        'c', CAST(:ctx AS jsonb)) "
                            "RETURNING vip_id"
                        ),
                        {"emb": _EMBEDDING_384, "ctx": "{}"},
                    )
                ).scalar_one()
                assert default_vip is None

                bogus_quality = (
                    await conn.execute(
                        text(
                            "INSERT INTO examples "
                            "(embedding, turn_text, draft_text, "
                            " corrected_text, context, quality) "
                            "VALUES (CAST(:emb AS vector), 'bogus', 'd', "
                            "        'c', CAST(:ctx AS jsonb), 'bogus') "
                            "RETURNING quality"
                        ),
                        {"emb": _EMBEDDING_384, "ctx": "{}"},
                    )
                ).scalar_one()
                assert bogus_quality == "bogus"

                policy_scope = (
                    await conn.execute(
                        text(
                            "INSERT INTO policies "
                            "(embedding, trigger_description, rule, vip_id) "
                            "VALUES (CAST(:emb AS vector), 'vip trigger', "
                            "        'vip rule', :vip) "
                            "RETURNING scope"
                        ),
                        {"emb": _EMBEDDING_384, "vip": vip_id},
                    )
                ).scalar_one()
                assert policy_scope == "all"

            with pytest.raises(IntegrityError):
                async with engine_post.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO examples "
                            "(embedding, turn_text, draft_text, "
                            " corrected_text, context, vip_id) "
                            "VALUES (CAST(:emb AS vector), 'badfk', 'd', "
                            "        'c', CAST(:ctx AS jsonb), "
                            "        gen_random_uuid())"
                        ),
                        {"emb": _EMBEDDING_384, "ctx": "{}"},
                    )
        finally:
            await engine_post.dispose()

        _alembic("downgrade", "028_link_events", db_url)

        engine_down = create_async_engine(db_url)
        try:
            assert not await _has_column(engine_down, "examples", "quality")
            assert not await _has_column(engine_down, "examples", "vip_id")
            assert not await _has_column(engine_down, "policies", "vip_id")
            assert await _has_column(engine_down, "policies", "scope")

            async with engine_down.begin() as conn:
                for index in _NEW_INDEXES:
                    assert await _index_count(conn, index) == 0, index
                for fk_name in _NEW_FKS:
                    assert await _constraint_count(conn, fk_name) == 0, fk_name
                for index in _HNSW:
                    assert await _index_count(conn, index) == 1, index

                examples_rows = (
                    await conn.execute(text("SELECT count(*) FROM examples"))
                ).scalar_one()
                policies_rows = (
                    await conn.execute(text("SELECT count(*) FROM policies"))
                ).scalar_one()
                vips_rows = (
                    await conn.execute(text("SELECT count(*) FROM vips"))
                ).scalar_one()
                assert examples_rows >= 1
                assert policies_rows >= 1
                assert vips_rows >= 1
        finally:
            await engine_down.dispose()
    finally:
        engine_drop = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
        async with engine_drop.begin() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_DB_NAME}"'))
        await engine_drop.dispose()
