"""feedback_quality: examples.quality + examples/policies.vip_id (FB-04)

Revision ID: 029_feedback_quality
Revises: 028_link_events
Create Date: 2026-08-16

Additive schema for quality feedback. ``quality`` is free Text (repo will
validate standard|gold later). ``vip_id IS NULL`` means global. Do not reuse
``policies.scope`` (channel axis). FKs have no ON DELETE (clearing vip_id
would promote VIP lessons to the global bank).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "029_feedback_quality"
down_revision: str | Sequence[str] | None = "028_link_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "examples",
        sa.Column(
            "quality",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )
    op.add_column(
        "examples",
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_examples_vip_id",
        "examples",
        "vips",
        ["vip_id"],
        ["id"],
    )
    op.create_index("ix_examples_vip_id", "examples", ["vip_id"])

    op.add_column(
        "policies",
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_policies_vip_id",
        "policies",
        "vips",
        ["vip_id"],
        ["id"],
    )
    op.create_index("ix_policies_vip_id", "policies", ["vip_id"])


def downgrade() -> None:
    op.drop_index("ix_policies_vip_id", table_name="policies")
    op.drop_constraint("fk_policies_vip_id", "policies", type_="foreignkey")
    op.drop_column("policies", "vip_id")
    op.drop_index("ix_examples_vip_id", table_name="examples")
    op.drop_constraint("fk_examples_vip_id", "examples", type_="foreignkey")
    op.drop_column("examples", "vip_id")
    op.drop_column("examples", "quality")
