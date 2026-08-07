"""agent_evolution_foundations: Fase 0 schema for the VIP agent evolution (6 tables)

Revision ID: 024_agent_evolution_foundations
Revises: 023_backfill_queue
Create Date: 2026-08-07

Implements SPEC-EVOLUCION-AGENTE v1.2 §Fase 0: the data foundations that
Fases 1–5 need to exist. Six tables:

- ``vip_profile`` — LLM-synthesized per-VIP profile (Fase 1 writer). DISTINTO
  de ``profiles`` (tabla vector, memories.py) y de ``/vip_profile`` (comando
  legacy admin sobre esa tabla vector).
- ``vip_profile_history`` — version snapshots for drift audit.
- ``vip_mood_state`` — 3-axis mood vector per VIP (Fase 3 writer).
- ``vip_trust_budget`` — trust score per (VIP, turn_category) (Fase 5 writer).
- ``turn_category_log`` — per-turn classification (Fase 2 writer; schema-only here).
- ``emotional_signal_log`` — emotional signal per turn (componente transversal).

Vocabulary is enforced with ``Text`` + ``CheckConstraint`` (the project never
uses native Postgres enums) and ASCII (``fatico``, ``revelacion_de_vida``),
consistent with the analyst intent/topic catalog.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "024_agent_evolution_foundations"
down_revision: str | Sequence[str] | None = "023_backfill_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vip_profile",
        sa.Column(
            "vip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vips.id"),
            primary_key=True,
        ),
        sa.Column(
            "stable_traits",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "recent_trend",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "sensitivities",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_synthesized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synthesis_trigger", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "synthesis_trigger IS NULL OR synthesis_trigger IN "
            "('volume','session_close','strong_signal','emotional_signal')",
            name="ck_vip_profile_synthesis_trigger",
        ),
    )
    op.create_table(
        "vip_profile_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "vip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profile_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "vip_mood_state",
        sa.Column(
            "vip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vips.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "axis_playful_serious",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "axis_warm_distant",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "axis_energy",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "vip_trust_budget",
        sa.Column(
            "vip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vips.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("turn_category", sa.Text(), nullable=False, primary_key=True),
        sa.Column(
            "trust_score",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "correction_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "autonomous_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_correction_at", sa.DateTime(timezone=True), nullable=True),
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
            "turn_category IN ('fatico','informativo','emocional','sensible')",
            name="ck_vip_trust_budget_turn_category",
        ),
    )
    op.create_table(
        "turn_category_log",
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
            nullable=True,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "category IN ('fatico','informativo','emocional','sensible')",
            name="ck_turn_category_log_category",
        ),
    )
    op.create_table(
        "emotional_signal_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "vip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vips.id"),
            nullable=True,
        ),
        sa.Column(
            "turn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("turns.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=False),
        sa.Column(
            "should_trigger_synthesis",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "should_escalate_to_owner",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("pipeline_would_have_escalated", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "signal_type IN "
            "('vulnerabilidad','angustia','revelacion_de_vida','ruptura_de_patron')",
            name="ck_emotional_signal_log_signal_type",
        ),
    )

    op.create_index(
        "ix_vip_profile_history_vip_id_created_at",
        "vip_profile_history",
        ["vip_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_vip_profile_history_created_at",
        "vip_profile_history",
        ["created_at"],
    )
    op.create_index(
        "ix_turn_category_log_chat_id_created_at",
        "turn_category_log",
        ["chat_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_turn_category_log_created_at",
        "turn_category_log",
        ["created_at"],
    )
    op.create_index(
        "ix_emotional_signal_log_vip_id_created_at",
        "emotional_signal_log",
        ["vip_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_emotional_signal_log_created_at",
        "emotional_signal_log",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_emotional_signal_log_created_at", table_name="emotional_signal_log")
    op.drop_index(
        "ix_emotional_signal_log_vip_id_created_at",
        table_name="emotional_signal_log",
    )
    op.drop_index("ix_turn_category_log_created_at", table_name="turn_category_log")
    op.drop_index(
        "ix_turn_category_log_chat_id_created_at",
        table_name="turn_category_log",
    )
    op.drop_index("ix_vip_profile_history_created_at", table_name="vip_profile_history")
    op.drop_index(
        "ix_vip_profile_history_vip_id_created_at",
        table_name="vip_profile_history",
    )
    op.drop_table("emotional_signal_log")
    op.drop_table("turn_category_log")
    op.drop_table("vip_trust_budget")
    op.drop_table("vip_mood_state")
    op.drop_table("vip_profile_history")
    op.drop_table("vip_profile")
