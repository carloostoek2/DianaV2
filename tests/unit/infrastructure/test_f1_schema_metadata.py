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


def test_orm_exposes_exactly_thirty_five_tables() -> None:
    """8 F1 + 8 F2 + 3 F3 + owner_marks + business_connections + runtime_timers + persona_versions + daily_message_limits + atencion_cycles + backfill_queue + 6 evo-agente (Fase 0) + ephemeral_events + link_events + turn_outcome_log (Fila 4) = 36 total."""
    assert F1_TABLES.issubset(set(Base.metadata.tables.keys()))
    assert len(Base.metadata.tables) == 36


def test_link_events_table_registers_expected_columns() -> None:
    assert "link_events" in Base.metadata.tables
    assert set(Base.metadata.tables["link_events"].columns.keys()) == {
        "id",
        "event_id",
        "user_id",
        "username",
        "channel_id",
        "channel_name",
        "reason",
        "vip_id",
        "state",
        "decision_at",
        "created_at",
    }


# Evo-Agente Fase 0: pin the 4 CHECK constraints and 6 index names offline so a
# rename in models.py / the 024 migration is caught by ``pytest tests/unit``.
_EVO_AGENTE_CHECKS = {
    "vip_profile": {"ck_vip_profile_synthesis_trigger"},
    "vip_trust_budget": {"ck_vip_trust_budget_turn_category"},
    "turn_category_log": {"ck_turn_category_log_category"},
    "emotional_signal_log": {"ck_emotional_signal_log_signal_type"},
}

_EVO_AGENTE_INDEXES = {
    "vip_profile_history": {
        "ix_vip_profile_history_vip_id_created_at",
        "ix_vip_profile_history_created_at",
    },
    "turn_category_log": {
        "ix_turn_category_log_chat_id_created_at",
        "ix_turn_category_log_created_at",
    },
    "emotional_signal_log": {
        "ix_emotional_signal_log_vip_id_created_at",
        "ix_emotional_signal_log_created_at",
    },
}


def test_turn_category_log_has_shadow_columns() -> None:
    """Fase 2 (migración 026): the ORM exposes the two shadow columns that the
    migration adds to ``turn_category_log`` — offline drift guard between the
    model and the migration (columns, NOT tables — the count stays 32)."""
    from diana.infrastructure.db.models import TurnCategoryLog

    cols = set(TurnCategoryLog.__table__.columns.keys())
    assert {"would_autonomous", "confidence"} <= cols


def test_evo_agente_check_constraint_names() -> None:
    """The 4 vocabulary CHECK constraints exist by exact name in the ORM."""
    for table_name, expected in _EVO_AGENTE_CHECKS.items():
        table = Base.metadata.tables[table_name]
        names = {c.name for c in table.constraints if c.name}
        assert expected.issubset(names), (table_name, names)


def test_evo_agente_index_names() -> None:
    """The 6 Fase 0 indexes exist by exact name in the ORM metadata."""
    for table_name, expected in _EVO_AGENTE_INDEXES.items():
        table = Base.metadata.tables[table_name]
        names = {i.name for i in table.indexes}
        assert expected.issubset(names), (table_name, names)


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

