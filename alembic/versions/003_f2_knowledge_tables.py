"""f2_knowledge_tables — 8 F2 tables + pgvector + HNSW indexes + seed flags

NOTE: HNSW indexes use non-concurrent CREATE INDEX inside the transaction
(acceptable for dev/staging; production migration should be manual).
pgvector extension is created IF NOT EXISTS (safe to re-run).

Revision ID: 003_f2_knowledge_tables
Revises: 002_turns_error
Create Date: 2026-07-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003_f2_knowledge_tables"
down_revision: Union[str, Sequence[str], None] = "002_turns_error"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector extension for vector(384) columns + HNSW index support.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # -- profiles --
    op.create_table(
        "profiles",
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.PrimaryKeyConstraint("vip_id"),
    )

    # -- memories --
    op.create_table(
        "memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- contexts --
    op.create_table(
        "contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- policies --
    op.create_table(
        "policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("trigger_description", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), server_default=sa.text("'all'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_query_id", postgresql.UUID(as_uuid=True), nullable=True),
        # NOTE: No FK constraint on source_query_id — intentionally loose-coupled
        # so gray_zone_queries can be cleaned independently without cascade issues.
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- examples --
    op.create_table(
        "examples",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("turn_text", sa.Text(), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_counter_example", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- staging_candidates --
    op.create_table(
        "staging_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- gray_zone_queries --
    op.create_table(
        "gray_zone_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("freeze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- learning_metrics --
    op.create_table(
        "learning_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- HNSW indexes (non-concurrent inside transaction for dev/staging)
    #   Production migration should create these manually with CONCURRENTLY.
    op.execute(
        "CREATE INDEX IF NOT EXISTS memories_embedding_idx "
        "ON memories USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS policies_embedding_idx "
        "ON policies USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS examples_embedding_idx "
        "ON examples USING hnsw (embedding vector_cosine_ops)"
    )

    # -- B-tree indexes for common lookups --
    op.execute(
        "CREATE INDEX IF NOT EXISTS memories_vip_id_idx ON memories (vip_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS policies_active_idx ON policies (is_active, valid_until)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS gray_zone_status_idx "
        "ON gray_zone_queries (status, freeze_until)"
    )

    # Seed feature flag defaults (static — runtime reading is F2 Item 3).
    op.execute(
        """
        INSERT INTO system_config (key, value) VALUES
        ('FEATURE_MEMORY_ENABLED', 'false'::jsonb),
        ('FEATURE_GRAY_ZONE_ENABLED', 'false'::jsonb),
        ('FEATURE_STAGING_ENABLED', 'false'::jsonb),
        ('FEATURE_SANDBOX_ENABLED', 'false'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    tables = (
        "learning_metrics",
        "gray_zone_queries",
        "staging_candidates",
        "examples",
        "policies",
        "contexts",
        "memories",
        "profiles",
    )
    for table in tables:
        op.drop_table(table)
    # vector extension intentionally retained (DB-level shared resource).
