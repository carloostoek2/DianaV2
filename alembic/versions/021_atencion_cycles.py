"""atencion_cycles: chat-level atencion lifecycle (F4)

Revision ID: 021_atencion_cycles
Revises: 020_gray_zone_bc
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021_atencion_cycles"
down_revision: str | Sequence[str] | None = "020_gray_zone_bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "atencion_cycles",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    op.drop_table("atencion_cycles")
