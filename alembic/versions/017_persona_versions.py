"""persona_versions: versioned persona catalog snapshots (owner admin).

Revision ID: 017_persona_versions
Revises: 016_runtime_timers_kind
Create Date: 2026-08-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "017_persona_versions"
down_revision: Union[str, Sequence[str], None] = "016_runtime_timers_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "persona_versions",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_persona_versions_active",
        "persona_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_persona_versions_created_at",
        "persona_versions",
        [sa.text("created_at DESC")],
    )
    op.execute(
        "INSERT INTO system_config (key, value) "
        "VALUES ('FEATURE_PERSONA_ADMIN_ENABLED', 'false'::jsonb) "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM system_config WHERE key = 'FEATURE_PERSONA_ADMIN_ENABLED'"
    )
    op.drop_index("ix_persona_versions_created_at", table_name="persona_versions")
    op.drop_index("uq_persona_versions_active", table_name="persona_versions")
    op.drop_table("persona_versions")
