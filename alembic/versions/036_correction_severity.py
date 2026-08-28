"""Add correction_severity to turn_outcome_log (SPEC-EA-07 severity shadow).

Revision ID: 036_correction_severity
Revises: 035_approval_photo_file_id
Create Date: 2026-08-28

SPEC-EA-07 (FEATURE_SEVERITY_TRUST_DECREMENT): the owner can tag a correction
as ``minor`` / ``moderate`` / ``major``. The column is a pure calibration
metadata shadow — it never feeds memories/examples/vip_profile and, while the
feature flag is OFF, never touches the trust score (byte-identical behavior).
The column is nullable — NULL keeps the pre-tagging behavior byte-for-byte
(flag off, or corrections resolved before the picker shipped). Vocabulary is
Text + CheckConstraint, never a native PG enum (pattern 030).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "036_correction_severity"
down_revision: str | Sequence[str] | None = "035_approval_photo_file_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turn_outcome_log",
        sa.Column("correction_severity", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_turn_outcome_log_correction_severity",
        "turn_outcome_log",
        "correction_severity IS NULL OR correction_severity "
        "IN ('minor','moderate','major')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_turn_outcome_log_correction_severity",
        "turn_outcome_log",
        type_="check",
    )
    op.drop_column("turn_outcome_log", "correction_severity")
