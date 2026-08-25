"""gray_zone_queries.proposed_rule / proposed_reply / proposal_source

Revision ID: 033_gray_zone_proposal
Revises: 032_escalation_events_business_connection
Create Date: 2026-08-25

FEATURE_GRAY_ZONE_PROPOSAL_ENABLED: when a gray-zone consult is raised, the
system may generate a RULE proposal (GrayZoneProposalService). The proposal is
persisted on the open query so the owner callback "💡 Usar regla propuesta"
(dp:) can recover the proposed rule by turn_id, and so freeze reminders can
re-send the same proposal. Columns, NOT tables — the table count stays the same.
Audit-only: the proposal is never written to memories/examples/policies; the
accepted rule still enters `policies` via the existing live-persist path.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "033_gray_zone_proposal"
down_revision: str | Sequence[str] | None = "032_escalation_events_business_connection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gray_zone_queries",
        sa.Column("proposed_rule", sa.Text(), nullable=True),
    )
    op.add_column(
        "gray_zone_queries",
        sa.Column("proposed_reply", sa.Text(), nullable=True),
    )
    op.add_column(
        "gray_zone_queries",
        sa.Column("proposal_source", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gray_zone_queries", "proposal_source")
    op.drop_column("gray_zone_queries", "proposed_reply")
    op.drop_column("gray_zone_queries", "proposed_rule")
