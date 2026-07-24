"""vip.frozen_until — nullable timestamp for VIP freeze gate

Revision ID: 004_vip_frozen_until
Revises: 003_f2_knowledge_tables
Create Date: 2026-07-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_vip_frozen_until"
down_revision: Union[str, Sequence[str], None] = "003_f2_knowledge_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vips",
        sa.Column("frozen_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vips", "frozen_until")
