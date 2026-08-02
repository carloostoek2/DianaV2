"""runtime_timers: nullable delivery_id, kind, payload (pre_delay VIP recovery).

Revision ID: 016_runtime_timers_kind
Revises: 015_business_connections
Create Date: 2026-08-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "016_runtime_timers_kind"
down_revision: Union[str, Sequence[str], None] = "015_business_connections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "runtime_timers",
        "delivery_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "runtime_timers",
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'delivery'"),
        ),
    )
    op.add_column(
        "runtime_timers",
        sa.Column("payload", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runtime_timers", "payload")
    op.drop_column("runtime_timers", "kind")
    # Fail if any NULL delivery_id rows exist; D1 rows must be cleared first.
    op.alter_column(
        "runtime_timers",
        "delivery_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=False,
    )
