"""business_connection_id on gray_zone_queries (F4).

Adds a nullable ``business_connection_id`` (Text) to ``gray_zone_queries`` so
the supervised-delivery flow can reconstruct the original ``IncomingTurn``
(which requires a non-empty business connection id) when synthesizing the
approval for a resolved/expired gray zone query.

Revision ID: 020_gray_zone_bc
Revises: 019_turn_trace_channel_type
Create Date: 2026-08-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_gray_zone_bc"
down_revision: Union[str, Sequence[str], None] = "019_turn_trace_channel_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "gray_zone_queries",
        sa.Column("business_connection_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gray_zone_queries", "business_connection_id")
