"""backfill_queue: persistent VIP profile backfill queue (F5 Pool 2)

Revision ID: 023_backfill_queue
Revises: 022_memory_status_source_turn
Create Date: 2026-08-05

Implements REQ-MEM-05: a durable per-VIP backfill queue so the memory
backfill survives restarts and is resumable window by window. One job per
VIP (partial unique index on active rows), lifecycle
``pending → processing → done | failed``, ``window_index`` tracks the next
window to extract, and ``state`` (jsonb) carries the facts accumulated from
previous windows (crash-safe resumption — "toda decisión es reconstruible a
partir de objetos persistidos").

The CHECK constraint enforces the status vocabulary at the schema level;
the partial unique index ``uq_backfill_queue_active_vip`` guarantees at most
one active (pending/processing) job per VIP, which is what makes the
``enqueue`` idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "023_backfill_queue"
down_revision: str | Sequence[str] | None = "022_memory_status_source_turn"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backfill_queue",
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
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("window_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
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
            "status IN ('pending','processing','done','failed')",
            name="ck_backfill_queue_status",
        ),
        # Fix round (L10): the done-outcome vocabulary is enforced at the
        # schema level too (M1 made ``done(outcome='failed')`` impossible;
        # ``disabled`` covers a flag turned off mid-run). The migration is
        # NOT yet applied to production → edited in place instead of adding
        # a 024 revision.
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('ok','empty_history','disabled')",
            name="ck_backfill_queue_outcome",
        ),
    )
    op.create_index(
        "ix_backfill_queue_status_created", "backfill_queue", ["status", "created_at"]
    )
    op.create_index(
        "uq_backfill_queue_active_vip",
        "backfill_queue",
        ["vip_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','processing')"),
    )


def downgrade() -> None:
    op.drop_index("uq_backfill_queue_active_vip", table_name="backfill_queue")
    op.drop_index("ix_backfill_queue_status_created", table_name="backfill_queue")
    op.drop_table("backfill_queue")
