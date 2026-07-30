"""Create business_connections table for BC lifecycle persistence.

Revision ID: 015_business_connections
Revises: 014_runtime_timers
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_business_connections"
down_revision: Union[str, Sequence[str], None] = "014_runtime_timers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "business_connections",
        sa.Column("business_connection_id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("user_chat_id", sa.BigInteger, nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("can_reply", sa.Boolean, nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("business_connections")
