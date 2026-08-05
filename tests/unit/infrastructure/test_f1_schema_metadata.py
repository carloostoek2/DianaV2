"""Offline F1 schema contract freezes (no Postgres required)."""

from __future__ import annotations

from pathlib import Path

from diana.infrastructure.db.models import (
    Base,
    EscalationEvent,
    MessageHistory,
    PendingApproval,
    PendingDelivery,
    PipelineTrace,
    SystemConfig,
    Turn,
    Vip,
)
# Import the repositories package and the inline-ORM repo modules so
# BusinessConnection + RuntimeTimer register on Base.metadata
# deterministically — the table-count test must not depend on incidental
# imports from other test modules.
import diana.infrastructure.db.repositories  # noqa: F401
from diana.infrastructure.db.repositories import (  # noqa: F401
    business_connections,
    runtime_timers,
)

F1_TABLES = frozenset(
    {
        "vips",
        "message_history",
        "turns",
        "pipeline_traces",
        "pending_deliveries",
        "pending_approvals",
        "escalation_events",
        "system_config",
    }
)

SEED_KEYS = frozenset(
    {
        "global_mode",
        "forbidden_keywords",
        "eval_thresholds",
        "trace_ttl_days",
    }
)


def test_orm_exposes_exactly_twenty_six_tables() -> None:
    """8 F1 + 8 F2 knowledge + 3 F3 proactivity + owner_marks + business_connections + runtime_timers + persona_versions + daily_message_limits + atencion_cycles + backfill_queue = 26 total."""
    assert F1_TABLES.issubset(set(Base.metadata.tables.keys()))
    assert len(Base.metadata.tables) == 26


def test_pipeline_traces_turn_id_fk_targets_turns() -> None:
    col = PipelineTrace.__table__.c.turn_id
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "turns"
    assert fks[0].column.name == "id"


def test_turn_scoped_tables_have_turn_id_fk() -> None:
    for model in (PendingDelivery, PendingApproval, EscalationEvent, PipelineTrace):
        col = model.__table__.c.turn_id
        assert any(fk.column.table.name == "turns" for fk in col.foreign_keys), model.__tablename__


def test_unique_constraints_on_vip_telegram_and_pending_approval_turn() -> None:
    assert Vip.__table__.c.telegram_user_id.unique is True
    assert PendingApproval.__table__.c.turn_id.unique is True


def test_escalation_notificado_is_non_null_bool() -> None:
    col = EscalationEvent.__table__.c.notificado
    assert col.nullable is False
    assert str(col.server_default.arg) == "false" or "false" in str(col.server_default.arg)


def test_status_server_defaults() -> None:
    assert "pending" in str(PendingDelivery.__table__.c.status.server_default.arg)
    assert "waiting" in str(PendingApproval.__table__.c.status.server_default.arg)


def test_turns_error_column_nullable_text() -> None:
    """Durable failure reason for mark_failed / A.6 (analista_schema_invalido)."""
    col = Turn.__table__.c.error
    assert col.nullable is True
    assert col.type.__class__.__name__ == "Text"


def test_migration_002_adds_turns_error() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "002_turns_error.py"
    )
    text = migration.read_text(encoding="utf-8")
    assert 'revision: str = "002_turns_error"' in text
    assert 'down_revision' in text and "001_f1_foundation" in text
    assert 'op.add_column' in text
    assert '"turns"' in text or "'turns'" in text
    assert '"error"' in text or "'error'" in text



def test_desc_indexes_present_in_orm_metadata() -> None:
    """ORM indexes must encode DESC expressions (match migration intent)."""
    def index_exprs(table_name: str, index_name: str) -> str:
        table = Base.metadata.tables[table_name]
        idx = table.indexes
        match = next(i for i in idx if i.name == index_name)
        return " ".join(str(el) for el in match.expressions).upper()

    assert "DESC" in index_exprs("message_history", "ix_message_history_chat_id_timestamp")
    assert "DESC" in index_exprs("turns", "ix_turns_chat_id_created_at")
    assert "DESC" in index_exprs("pipeline_traces", "ix_pipeline_traces_vip_id_created_at")
    assert "DESC" in index_exprs("pipeline_traces", "ix_pipeline_traces_chat_id_created_at")
    assert "pipeline_traces_created_at_idx" in {i.name for i in Base.metadata.tables["pipeline_traces"].indexes}
    names = {i.name for i in Base.metadata.tables["pipeline_traces"].indexes}
    assert "ix_pipeline_traces_chat_id_created_at" in names


def test_migration_003_creates_f2_knowledge_tables() -> None:
    """Migration 003 must create 8 F2 tables (profiles, memories, contexts,
    policies, examples, staging_candidates, gray_zone_queries, learning_metrics)."""
    migration = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "003_f2_knowledge_tables.py"
    )
    text = migration.read_text(encoding="utf-8")
    assert 'revision: str = "003_f2_knowledge_tables"' in text
    assert 'down_revision' in text and "002_turns_error" in text
    # All 8 F2 tables must be created.
    f2_tables = (
        "profiles",
        "memories",
        "contexts",
        "policies",
        "examples",
        "staging_candidates",
        "gray_zone_queries",
        "learning_metrics",
    )
    for table in f2_tables:
        assert f'"{table}"' in text or f"'{table}'" in text
    # pgvector extension and Vector(384) columns.
    assert "CREATE EXTENSION IF NOT EXISTS vector" in text
    # Seed flags for F2 runtime config.
    assert "FEATURE_MEMORY_ENABLED" in text
    assert "FEATURE_GRAY_ZONE_ENABLED" in text
    assert "FEATURE_STAGING_ENABLED" in text
    assert "FEATURE_SANDBOX_ENABLED" in text


def test_migration_seed_keys_allowlist() -> None:
    migration = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "001_f1_foundation.py"
    text = migration.read_text(encoding="utf-8")
    for key in SEED_KEYS:
        assert f"'{key}'" in text
    # Seed must not INSERT owner id (comment may mention it as intentionally omitted).
    assert "('owner_telegram_id'" not in text
    assert '"owner_telegram_id"' not in text
    assert "ON CONFLICT (key) DO NOTHING" in text
    assert "nullable=False" in text  # notificado alignment among others

def test_migration_011_pipeline_traces_chat_index() -> None:
    """Migration 011 indexes pipeline_traces (chat_id, created_at DESC)."""
    migration = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "011_pipeline_traces_chat_intents_idx.py"
    )
    text = migration.read_text(encoding="utf-8")
    assert 'revision: str = "011_pipeline_traces_chat_intents_idx"' in text
    assert "010_owner_marks" in text
    assert "ix_pipeline_traces_chat_id_created_at" in text
    assert "created_at DESC" in text

