"""Offline source + ORM asserts for feedback quality schema (029)."""

from __future__ import annotations

from pathlib import Path

from diana.infrastructure.db.models import Base, Example, Policy

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_029 = REPO_ROOT / "alembic" / "versions" / "029_feedback_quality.py"
REVISION = "029_feedback_quality"


def _migration_text() -> str:
    assert MIGRATION_029.is_file(), f"missing migration: {MIGRATION_029}"
    return MIGRATION_029.read_text(encoding="utf-8")


def test_029_file_exists_and_revision_chain() -> None:
    assert MIGRATION_029.is_file()
    text = _migration_text()
    assert f'revision: str = "{REVISION}"' in text
    assert (
        'down_revision: str | Sequence[str] | None = "028_link_events"'
        in text
    )
    assert len(REVISION) <= 32
    assert (
        'down_revision: str | Sequence[str] | None = "027_ephemeral_events"'
        not in text
    )


def test_029_adds_quality_and_vip_id_columns() -> None:
    text = _migration_text()
    assert "op.add_column" in text
    assert '"examples"' in text
    assert '"quality"' in text
    assert "sa.Text()" in text or "sa.Text" in text
    assert "VARCHAR" not in text
    assert "String(" not in text
    assert "nullable=False" in text
    assert "server_default=sa.text(\"'standard'\")" in text
    assert "'standard'" in text
    assert "postgresql.UUID" in text
    assert '"vip_id"' in text
    assert "nullable=True" in text
    assert '"policies"' in text
    compact = " ".join(text.split())
    assert (
        'op.create_foreign_key( "fk_examples_vip_id", "examples", "vips", '
        '["vip_id"], ["id"]' in compact
    )
    assert (
        'op.create_foreign_key( "fk_policies_vip_id", "policies", "vips", '
        '["vip_id"], ["id"]' in compact
    )
    assert 'op.create_index("ix_examples_vip_id", "examples", ["vip_id"])' in text
    assert 'op.create_index("ix_policies_vip_id", "policies", ["vip_id"])' in text
    assert '"vips"' in text
    assert '"id"' in text


def test_029_has_no_quality_check_and_no_ondelete() -> None:
    text = _migration_text()
    assert "CheckConstraint" not in text
    assert "create_check_constraint" not in text
    assert "ck_examples_quality" not in text
    assert "SET NULL" not in text
    assert "ondelete" not in text
    assert "op.alter_column" not in text
    assert "FEATURE_QUALITY" not in text


def test_029_downgrade_drops_indexes_fks_and_columns() -> None:
    text = _migration_text()
    downgrade = text.split("def downgrade")[1]
    assert 'op.drop_index("ix_policies_vip_id", table_name="policies")' in downgrade
    assert (
        'op.drop_constraint("fk_policies_vip_id", "policies", type_="foreignkey")'
        in downgrade
    )
    assert 'op.drop_column("policies", "vip_id")' in downgrade
    assert 'op.drop_index("ix_examples_vip_id", table_name="examples")' in downgrade
    assert (
        'op.drop_constraint("fk_examples_vip_id", "examples", type_="foreignkey")'
        in downgrade
    )
    assert 'op.drop_column("examples", "vip_id")' in downgrade
    assert 'op.drop_column("examples", "quality")' in downgrade

    policies_fk_drop = downgrade.index(
        'op.drop_constraint("fk_policies_vip_id", "policies", type_="foreignkey")'
    )
    policies_col_drop = downgrade.index('op.drop_column("policies", "vip_id")')
    examples_fk_drop = downgrade.index(
        'op.drop_constraint("fk_examples_vip_id", "examples", type_="foreignkey")'
    )
    examples_col_drop = downgrade.index('op.drop_column("examples", "vip_id")')
    assert policies_col_drop > policies_fk_drop
    assert examples_col_drop > examples_fk_drop


def _assert_vip_fk(column) -> None:
    fks = list(column.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "vips"
    assert fk.column.name == "id"
    assert fk.ondelete is None


def test_orm_example_and_policy_expose_feedback_columns() -> None:
    assert "quality" in Example.__table__.c
    assert "vip_id" in Example.__table__.c
    assert "vip_id" in Policy.__table__.c

    quality = Example.__table__.c.quality
    assert quality.nullable is False
    assert "standard" in str(quality.server_default.arg)
    assert quality.default.arg == "standard"

    assert Example.__table__.c.vip_id.nullable is True
    assert Policy.__table__.c.vip_id.nullable is True
    _assert_vip_fk(Example.__table__.c.vip_id)
    _assert_vip_fk(Policy.__table__.c.vip_id)

    assert "ix_examples_vip_id" in {i.name for i in Example.__table__.indexes}
    assert "ix_policies_vip_id" in {i.name for i in Policy.__table__.indexes}

    assert "scope" in Policy.__table__.c
    assert "quality" not in Policy.__table__.c
    # 35 pre-Fila-4 tables + turn_outcome_log (030) + profile_synthesis_queue (031).
    assert len(Base.metadata.tables) == 36
