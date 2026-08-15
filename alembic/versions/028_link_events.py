"""link_events: ledger for Lucien→Diana kick link decisions.

Revision ID: 028_link_events
Revises: 027_ephemeral_events
Create Date: 2026-08-15

One row per ``[LINK]`` kick event received from the Lucien bot. The row is
persisted before the VIP check so the decision lifecycle (pending → notified →
decided_* / ignored_not_vip) is reconstructible even for non-VIP users.
``vip_id`` is a loose UUID (no FK) resolved after the event arrives.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "028_link_events"
down_revision: str | Sequence[str] | None = "027_ephemeral_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "link_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_name", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("link_events")
