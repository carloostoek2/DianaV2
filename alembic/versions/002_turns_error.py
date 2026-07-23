"""turns.error — durable failure reason (A.6 / mark_failed)

Revision ID: 002_turns_error
Revises: 001_f1_foundation
Create Date: 2026-07-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_turns_error"
down_revision: Union[str, Sequence[str], None] = "001_f1_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "turns",
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("turns", "error")
