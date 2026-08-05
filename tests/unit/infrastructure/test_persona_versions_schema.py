"""Offline source + ORM asserts for persona_versions schema (017)."""

from __future__ import annotations

from pathlib import Path

from diana.infrastructure.db.models import Base, PersonaVersion

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_017 = REPO_ROOT / "alembic" / "versions" / "017_persona_versions.py"
MIGRATION_018 = REPO_ROOT / "alembic" / "versions" / "018_channel_type_atencion.py"

REVISION = "017_persona_versions"

EXPECTED_COLUMNS = {
    "id",
    "version",
    "channel_type",
    "source",
    "payload",
    "is_active",
    "created_by",
    "created_at",
    "applied_at",
}

# Migration 017 creates the table without channel_type (added in 018).
MIGRATION_017_COLUMNS = {
    "id",
    "version",
    "source",
    "payload",
    "is_active",
    "created_by",
    "created_at",
    "applied_at",
}


def _migration_text() -> str:
    assert MIGRATION_017.is_file(), f"missing migration: {MIGRATION_017}"
    return MIGRATION_017.read_text(encoding="utf-8")


def test_017_file_exists_and_revision_chain() -> None:
    assert MIGRATION_017.is_file()
    text = _migration_text()
    assert f'revision: str = "{REVISION}"' in text
    assert (
        'down_revision: Union[str, Sequence[str], None] = "016_runtime_timers_kind"'
        in text
    )
    assert len(REVISION) <= 32


def test_017_creates_persona_versions_table_and_columns() -> None:
    text = _migration_text()
    assert '"persona_versions"' in text or "'persona_versions'" in text
    for column in MIGRATION_017_COLUMNS:
        assert f'"{column}"' in text or f"'{column}'" in text
    assert "JSONB" in text
    assert "gen_random_uuid()" in text


def test_017_partial_unique_active_index() -> None:
    text = _migration_text()
    assert "uq_persona_versions_active" in text
    assert "unique=True" in text
    assert "postgresql_where" in text
    assert "is_active" in text


def test_017_created_at_desc_index() -> None:
    text = _migration_text()
    assert "ix_persona_versions_created_at" in text
    assert "created_at DESC" in text


def test_017_unique_version_index() -> None:
    import re

    text = _migration_text()
    assert "uq_persona_versions_version" in text
    assert re.search(
        r'"uq_persona_versions_version".*?unique=True', text, re.DOTALL
    ) is not None
    assert '"version"],' in text


def test_017_seeds_feature_flag_in_system_config() -> None:
    text = _migration_text()
    assert "FEATURE_PERSONA_ADMIN_ENABLED" in text
    assert "'false'::jsonb" in text
    assert "ON CONFLICT (key) DO NOTHING" in text


def test_017_downgrade_drops_table_and_flag() -> None:
    text = _migration_text()
    assert "op.drop_table(\"persona_versions\")" in text
    assert "DELETE FROM system_config" in text
    assert "FEATURE_PERSONA_ADMIN_ENABLED" in text


def test_orm_daily_message_limits_registered() -> None:
    """F4: daily_message_limits table exists with (chat_id, fecha_local) PK."""
    assert "daily_message_limits" in Base.metadata.tables
    from diana.infrastructure.db.models import DailyMessageLimit

    table = DailyMessageLimit.__table__
    assert [col.name for col in table.primary_key.columns] == [
        "chat_id",
        "fecha_local",
    ]
    assert "count" in table.c.keys()


def test_018_channel_type_migration_source() -> None:
    """Migration 018 adds channel_type, multi-channel index, limits table, seed."""
    assert MIGRATION_018.is_file(), f"missing migration: {MIGRATION_018}"
    text = MIGRATION_018.read_text(encoding="utf-8")
    assert 'revision: str = "018_channel_type_atencion"' in text
    assert "017_persona_versions" in text
    assert "op.add_column" in text
    assert '"channel_type"' in text or "'channel_type'" in text
    assert '"daily_message_limits"' in text or "'daily_message_limits'" in text
    assert "FEATURE_GENERAL_MODE_ENABLED" in text
    assert "channel_type = 'atencion'" in text or "'atencion'" in text
    # downgrade reverses: drop limits table, column, and re-create single-channel index.
    assert "op.drop_table(\"daily_message_limits\")" in text
    assert "op.drop_column(\"persona_versions\", \"channel_type\")" in text
    assert "op.drop_index(\"uq_persona_versions_active\", table_name=\"persona_versions\")" in text


def test_018_downgrade_removes_all_atencion_rows_before_index_recreate() -> None:
    """B5: downgrade deactivates + deletes EVERY atencion row (seed and owner
    saved) so the single-channel ``(is_active) WHERE is_active`` index recreate
    cannot abort on a duplicate-active row."""
    text = MIGRATION_018.read_text(encoding="utf-8")
    downgrade = text.split("def downgrade")[1]
    # Deactivate + delete ALL atencion rows (seed AND owner-saved) so the
    # single-channel active index recreate below never hits a duplicate-active.
    assert "UPDATE persona_versions SET is_active = false" in downgrade
    assert "DELETE FROM persona_versions" in downgrade
    assert "channel_type = 'atencion'" in downgrade
    # the seed-only delete (previous bug) is gone
    assert "source = 'seed'" not in downgrade


def test_018_seed_matches_static_atencion_catalog() -> None:
    """B6: the migration seed payload equals the packaged persona_atencion.json
    catalog (single source of truth), so the two can never drift."""
    import importlib.util
    import sys

    from diana.cognitive.persona_catalog import load_persona_atencion_catalog

    spec = importlib.util.spec_from_file_location(
        "migration_018", MIGRATION_018
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    try:
        seed = module._load_atencion_seed()
    finally:
        sys.modules.pop("migration_018", None)
    assert seed == load_persona_atencion_catalog()
    # B3: neutral service tone — no leaked locations, personal routine or
    # forced-laughter slang in the atencion schedule.
    schedule = seed["schedule"]
    for respuesta in schedule["default_responses"]:
        low = respuesta.lower()
        assert "jsjs" not in low
        assert "mil cosas" not in low
        assert "zombi" not in low
    for bloque in schedule["bloques"]:
        low = bloque["actividad"].lower()
        for leaked in (
            "instituto",
            "casa hogar",
            "clase de inglés",
            "diplomado",
            "su hermana",
            "sus casas",
            "niños",
            "adicciones",
        ):
            assert leaked not in low, f"atencion schedule leaks {leaked!r}"


def test_orm_persona_version_registered_with_schema() -> None:
    assert "persona_versions" in Base.metadata.tables
    columns = set(PersonaVersion.__table__.c.keys())
    assert columns == EXPECTED_COLUMNS

    names = {i.name for i in PersonaVersion.__table__.indexes}
    assert "uq_persona_versions_active" in names
    assert "ix_persona_versions_created_at" in names
    assert "uq_persona_versions_version" in names

    active_idx = next(
        i for i in PersonaVersion.__table__.indexes
        if i.name == "uq_persona_versions_active"
    )
    assert active_idx.unique is True
    # F4 multi-channel: the active constraint is scoped per channel.
    assert [col.name for col in active_idx.columns] == ["channel_type", "is_active"]
    assert active_idx.dialect_options["postgresql"]["where"] is not None

    version_idx = next(
        i for i in PersonaVersion.__table__.indexes
        if i.name == "uq_persona_versions_version"
    )
    assert version_idx.unique is True
