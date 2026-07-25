"""Add timings JSONB column to pipeline_traces + created_at DESC index

Revision ID: 005_trace_timings
Revises: 004_vip_frozen_until
Create Date: 2026-07-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision: str = "005_trace_timings"
down_revision: Union[str, Sequence[str], None] = "004_vip_frozen_until"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipeline_traces",
        sa.Column("timings", JSONB, server_default=text("'{}'::jsonb")),
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "pipeline_traces_created_at_idx",
            "pipeline_traces",
            [sa.text("created_at DESC")],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "pipeline_traces_created_at_idx",
            postgresql_concurrently=True,
        )
    op.drop_column("pipeline_traces", "timings")
