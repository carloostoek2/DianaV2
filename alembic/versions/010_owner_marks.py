"""owner_marks table for false-positive escalation marks (R5 residual).

Revision ID: 010_owner_marks
Revises: 009_f3_calibration
Create Date: 2026-07-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_owner_marks"
down_revision: Union[str, Sequence[str], None] = "009_f3_calibration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "owner_marks",
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("turn_id", "kind", name="pk_owner_marks"),
    )
    op.create_index(
        "ix_owner_marks_kind_created",
        "owner_marks",
        ["kind", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_owner_marks_kind_created", table_name="owner_marks")
    op.drop_table("owner_marks")
