"""agent_evolution_turn_category_columns: turn_category_log shadow columns (Fase 2)

Revision ID: 026_agent_evolution_turn_category_columns
Revises: 025_agent_evolution_synthesis_index
Create Date: 2026-08-07

Fase 2 shadow measurement: ``would_autonomous`` (habría autoenviado, fast-lane)
+ ``confidence`` (modo "no estoy seguro" del clasificador). Columns, NOT tables
— table count stays 32. The category CHECK is NOT extended: 'no_estoy_seguro'
is expressed via confidence < classifier_confidence_min.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "026_agent_evolution_turn_category_columns"
down_revision: str | Sequence[str] | None = "025_agent_evolution_synthesis_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turn_category_log", sa.Column("would_autonomous", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "turn_category_log", sa.Column("confidence", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("turn_category_log", "would_autonomous")
    op.drop_column("turn_category_log", "confidence")
