"""escalation_events.business_connection_id (owner escalation reply)

Revision ID: 032_escalation_events_business_connection
Revises: 031_profile_synthesis_queue
Create Date: 2026-08-23

The owner escalation DM now offers "Responder al VIP": the free-text reply is
delivered to the escalated chat through the BehaviorEngine, which requires the
chat's business_connection_id. The turn/approval tables do not carry it, so the
escalation record stores it at notify time. Column, NOT table — table count
stays the same.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "032_escalation_events_business_connection"
down_revision: str | Sequence[str] | None = "031_profile_synthesis_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "escalation_events",
        sa.Column("business_connection_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("escalation_events", "business_connection_id")
