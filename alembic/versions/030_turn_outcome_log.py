"""turn_outcome_log: Fila 4 learning-circle ledger (SPEC-AUTONOMIA-CALIBRACION §7)

Revision ID: 030_turn_outcome_log
Revises: 029_feedback_quality
Create Date: 2026-08-22

The Fila 4 ledger: one row per finished VIP turn written post-turn (shadow
verdict + draft score), updated when the owner resolves (owner outcome + sent
score + quality delta) and when the VIP reaction window closes (vip_signal).

ANTI-CONTAMINATION: pure calibration metric — must never feed ``memories``,
``examples`` or ``vip_profile``. Vocabulary is Text + CheckConstraint (never
native PG enums), consistent with the agent-evolution tables (migration 024).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "030_turn_outcome_log"
down_revision: str | Sequence[str] | None = "029_feedback_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_outcome_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("turns.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "vip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vips.id"),
            nullable=False,
        ),
        sa.Column("shadow_verdict", sa.Text(), nullable=False),
        sa.Column("shadow_reason", sa.Text(), nullable=True),
        sa.Column("owner_outcome", sa.Text(), nullable=True),
        sa.Column("draft_score", sa.Float(), nullable=True),
        sa.Column("sent_score", sa.Float(), nullable=True),
        sa.Column("quality_delta", sa.Float(), nullable=True),
        sa.Column(
            "blocked_dims",
            postgresql.JSONB(),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("vip_signal", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "shadow_verdict IN ('send','blocked','escalate','doctrine')",
            name="ck_turn_outcome_log_shadow_verdict",
        ),
        sa.CheckConstraint(
            "owner_outcome IS NULL OR owner_outcome IN "
            "('approved_as_is','corrected','escalated')",
            name="ck_turn_outcome_log_owner_outcome",
        ),
        sa.CheckConstraint(
            "vip_signal IS NULL OR vip_signal IN "
            "('positive','neutral','negative','silence')",
            name="ck_turn_outcome_log_vip_signal",
        ),
    )
    op.create_index(
        "ix_turn_outcome_log_vip_id_created_at",
        "turn_outcome_log",
        ["vip_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_turn_outcome_log_created_at",
        "turn_outcome_log",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_turn_outcome_log_created_at", table_name="turn_outcome_log")
    op.drop_index(
        "ix_turn_outcome_log_vip_id_created_at",
        table_name="turn_outcome_log",
    )
    op.drop_table("turn_outcome_log")
