"""profile_synthesis_queue: durable synthesis queue (Fila 4 C4, SPEC §5 C4)

Revision ID: 031_profile_synthesis_queue
Revises: 030_turn_outcome_log
Create Date: 2026-08-22

Persists the in-memory profile-synthesis guard so pending/processing
resynthesis survives restarts. ``trigger`` vocab mirrors the agent-evolution
CHECK constraints (Text, never native PG enums).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "031_profile_synthesis_queue"
down_revision: str | Sequence[str] | None = "030_turn_outcome_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile_synthesis_queue",
        sa.Column(
            "vip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vips.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "trigger IN "
            "('volume','session_close','strong_signal','emotional_signal')",
            name="ck_profile_synthesis_queue_trigger",
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing')",
            name="ck_profile_synthesis_queue_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("profile_synthesis_queue")
