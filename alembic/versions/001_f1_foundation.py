"""f1_foundation — 8 F1 tables + non-secret system_config seed

Revision ID: 001_f1_foundation
Revises:
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_f1_foundation"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

F1_TABLES = (
    "pipeline_traces",
    "pending_deliveries",
    "pending_approvals",
    "escalation_events",
    "message_history",
    "turns",
    "vips",
    "system_config",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "vips",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )

    op.create_table(
        "message_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_message_history_chat_id_timestamp",
        "message_history",
        ["chat_id", sa.text("timestamp DESC")],
        unique=False,
    )

    op.create_table(
        "turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("trigger_message_id", sa.BigInteger(), nullable=True),
        sa.Column("superseded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_turns_chat_id_status", "turns", ["chat_id", "status"], unique=False)
    op.create_index(
        "ix_turns_chat_id_created_at",
        "turns",
        ["chat_id", sa.text("created_at DESC")],
        unique=False,
    )

    op.create_table(
        "pipeline_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("comprehension", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("retrieved", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("generated_text", sa.Text(), nullable=True),
        sa.Column("evaluation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("delivery_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_traces_turn_id", "pipeline_traces", ["turn_id"], unique=False)
    op.create_index(
        "ix_pipeline_traces_vip_id_created_at",
        "pipeline_traces",
        ["vip_id", sa.text("created_at DESC")],
        unique=False,
    )

    op.create_table(
        "pending_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("business_connection_id", sa.Text(), nullable=False),
        sa.Column("texts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pending_deliveries_status_scheduled_at",
        "pending_deliveries",
        ["status", "scheduled_at"],
        unique=False,
    )

    op.create_table(
        "pending_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("business_connection_id", sa.Text(), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("cognitive_summary", sa.Text(), nullable=True),
        sa.Column("evaluation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'waiting'"), nullable=False),
        sa.Column("owner_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id"),
    )
    op.create_index(
        "ix_pending_approvals_status_created_at",
        "pending_approvals",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "escalation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("notificado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "system_config",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    # Non-secret seed only. owner_telegram_id lives in Settings/env (not seeded).
    # ON CONFLICT keeps re-application of seed SQL safe outside transactional upgrade.
    op.execute(
        """
        INSERT INTO system_config (key, value) VALUES
        ('global_mode', '"supervised"'::jsonb),
        ('forbidden_keywords', '["pago", "transferencia", "eres un bot", "reclamación"]'::jsonb),
        ('eval_thresholds', '{"safety": 0.3}'::jsonb),
        ('trace_ttl_days', '30'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    # Drop dependents first (FK order).
    # pgcrypto is intentionally retained: extensions are DB-level shared resources
    # and other apps/schemas may depend on them.
    for table in F1_TABLES:
        op.drop_table(table)
