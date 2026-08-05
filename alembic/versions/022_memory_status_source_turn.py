"""memory_status_source_turn: memories gains status + source_turn_id (F5-09)

Revision ID: 022_memory_status_source_turn
Revises: 021_atencion_cycles
Create Date: 2026-08-05

Adds the REQ-MEM-09 columns to ``memories``: a NOT NULL ``status`` with
server default ``'auto'`` (table is empty today, so no data backfill needed),
a nullable soft-reference ``source_turn_id`` (no FK — same loose coupling as
``Policy.source_query_id``), and the ``(vip_id, status)`` index that backs the
visibility filter in ``find_by_vip_and_similarity``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "022_memory_status_source_turn"
down_revision: str | Sequence[str] | None = "021_atencion_cycles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("status", sa.Text(), nullable=False, server_default="auto"),
    )
    op.add_column(
        "memories",
        sa.Column(
            "source_turn_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    # Fix round (L3): the visibility gate depends on `status` — enforce the
    # vocabulary at the schema level (defense in depth with the DTO/repo).
    op.create_check_constraint(
        "ck_memories_status",
        "memories",
        "status IN ('auto', 'pending_owner', 'approved', 'discarded')",
    )
    op.create_index(
        "ix_memories_vip_id_status",
        "memories",
        ["vip_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_memories_vip_id_status", table_name="memories")
    op.drop_constraint("ck_memories_status", "memories", type_="check")
    op.drop_column("memories", "source_turn_id")
    op.drop_column("memories", "status")
