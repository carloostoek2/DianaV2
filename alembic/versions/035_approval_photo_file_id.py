"""Add photo_file_id to pending_approvals (image vision owner DM).

Revision ID: 035_approval_photo_file_id
Revises: 034_enable_rls_public
Create Date: 2026-08-26

FEATURE_IMAGE_VISION_ENABLED: when an inbound VIP message carries a photo, the
approval DM sent to the owner attaches that same photo (Telegram file_id) so
she can judge what Diana saw. The column is nullable — NULL keeps the classic
text-only approval behavior byte-for-byte (flag off, or messages without a
photo, or non-VIP channels that never had a photo).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "035_approval_photo_file_id"
down_revision: str | Sequence[str] | None = "034_enable_rls_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pending_approvals",
        sa.Column("photo_file_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pending_approvals", "photo_file_id")
