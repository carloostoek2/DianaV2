"""Create runtime_timers table for crash-recovery timer persistence.

Revision ID: 014_runtime_timers
Revises: 013_rename_staging_candidate_type
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "014_runtime_timers"
down_revision: Union[str, Sequence[str], None] = "013_rename_staging_candidate_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_timers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("turn_id", UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_delay_seconds", sa.Float, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_runtime_timers_status_created_at",
        "runtime_timers",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_timers_status_created_at", table_name="runtime_timers")
    op.drop_table("runtime_timers")
