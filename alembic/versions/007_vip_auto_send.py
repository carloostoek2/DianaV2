"""vip.auto_send — per-VIP autonomous override (REQ-MODE-08)

Revision ID: 007_vip_auto_send
Revises: 006_f3_flags_thresholds
Create Date: 2026-07-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_vip_auto_send"
down_revision: Union[str, Sequence[str], None] = "006_f3_flags_thresholds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vips",
        sa.Column(
            "auto_send",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("vips", "auto_send")
