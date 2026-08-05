"""channel_type multi-channel persona + daily_message_limits (F4 general mode).

Adds ``persona_versions.channel_type`` (default ``'vip'``), scopes the active
constraint to ``(channel_type, is_active)``, creates the ``daily_message_limits``
table (Item 2 wiring later), seeds the ``atencion`` persona catalog as a real row
plus the ``FEATURE_GENERAL_MODE_ENABLED`` informational flag.

Revision ID: 018_channel_type_atencion
Revises: 017_persona_versions
Create Date: 2026-08-05
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "018_channel_type_atencion"
down_revision: Union[str, Sequence[str], None] = "017_persona_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Single source of truth for the atencion persona catalog: the packaged static
# file used by ``get_persona_atencion_catalog``. The seed row is the same JSONB
# payload the runtime static fallback loads, so the seed can never drift from
# ``persona_atencion.json`` (guard test: test_018_seed_matches_static_catalog).
_ATENCION_JSON = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "diana"
    / "config"
    / "persona_atencion.json"
)


def _load_atencion_seed() -> dict:
    """Read the atencion persona catalog from ``persona_atencion.json``."""
    return json.loads(_ATENCION_JSON.read_text(encoding="utf-8"))


def upgrade() -> None:
    op.add_column(
        "persona_versions",
        sa.Column(
            "channel_type",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'vip'"),
        ),
    )
    op.drop_index("uq_persona_versions_active", table_name="persona_versions")
    op.create_index(
        "uq_persona_versions_active",
        "persona_versions",
        ["channel_type", "is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "daily_message_limits",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("fecha_local", sa.Date(), nullable=False),
        sa.Column(
            "count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("chat_id", "fecha_local"),
    )
    op.execute(
        "INSERT INTO system_config (key, value) "
        "VALUES ('FEATURE_GENERAL_MODE_ENABLED', 'false'::jsonb) "
        "ON CONFLICT (key) DO NOTHING"
    )
    # Seed version is computed at migration time as max(version)+1 over the
    # GLOBAL counter (uq_persona_versions_version is global). On a fresh DB it
    # lands at 1; on an existing DB that already has VIP v1 it lands at 2, so
    # the seed can never collide with the next owner save. ON CONFLICT DO
    # NOTHING stays only as belt-and-suspenders for a partially-applied run.
    seed_version = op.get_bind().execute(
        sa.text(
            "SELECT COALESCE(MAX(version), 0) FROM persona_versions"
        )
    ).scalar_one()
    op.get_bind().execute(
        sa.text(
            "INSERT INTO persona_versions "
            "(channel_type, version, source, payload, is_active) "
            "VALUES (:channel_type, :version, :source, CAST(:payload AS jsonb), :is_active) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "channel_type": "atencion",
            "version": int(seed_version) + 1,
            "source": "seed",
            "payload": json.dumps(_load_atencion_seed()),
            "is_active": True,
        },
    )


def downgrade() -> None:
    # Remove EVERY atencion row (seed and owner-saved) and deactivate them
    # first: the single-channel ``(is_active) WHERE is_active`` index recreated
    # below would otherwise abort on a duplicate-active row when an owner-saved
    # atencion version coexists with an active VIP one.
    op.execute(
        "UPDATE persona_versions SET is_active = false "
        "WHERE channel_type = 'atencion'"
    )
    op.execute(
        "DELETE FROM persona_versions WHERE channel_type = 'atencion'"
    )
    op.drop_table("daily_message_limits")
    op.drop_index("uq_persona_versions_active", table_name="persona_versions")
    op.create_index(
        "uq_persona_versions_active",
        "persona_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.drop_column("persona_versions", "channel_type")
    op.execute(
        "DELETE FROM system_config WHERE key = 'FEATURE_GENERAL_MODE_ENABLED'"
    )
