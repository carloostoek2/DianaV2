"""channel_type on turns/pipeline_traces + gray_zone_queries.chat_id (F4).

Adds ``channel_type`` (default ``'vip'``) to ``turns`` and
``pipeline_traces`` so atencion-channel rows are tagged at the write path,
and a nullable ``chat_id`` (with index) to ``gray_zone_queries`` so the
atencion chat freeze resolves by chat instead of VIP id.

Revision ID: 019_turn_trace_channel_type
Revises: 018_channel_type_atencion
Create Date: 2026-08-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019_turn_trace_channel_type"
down_revision: Union[str, Sequence[str], None] = "018_channel_type_atencion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "turns",
        sa.Column(
            "channel_type",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'vip'"),
        ),
    )
    op.add_column(
        "pipeline_traces",
        sa.Column(
            "channel_type",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'vip'"),
        ),
    )
    op.add_column(
        "gray_zone_queries",
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_gray_zone_queries_chat_id",
        "gray_zone_queries",
        ["chat_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_gray_zone_queries_chat_id", table_name="gray_zone_queries")
    op.drop_column("gray_zone_queries", "chat_id")
    op.drop_column("pipeline_traces", "channel_type")
    op.drop_column("turns", "channel_type")
