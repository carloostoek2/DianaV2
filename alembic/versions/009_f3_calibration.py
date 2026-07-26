"""Seed calibration JSON blob for F3 CalibrationService (SPEC §5.5 / §7.2).

Revision ID: 009_f3_calibration
Revises: 008_recontact_promo
Create Date: 2026-07-26

Does not ALTER learning_metrics (EAV). Feature flag FEATURE_CALIBRATION_ENABLED
already seeded false in 006_f3_flags_thresholds.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_f3_calibration"
down_revision: Union[str, Sequence[str], None] = "008_recontact_promo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO system_config (key, value) VALUES
        ('calibration',
         '{"window_days": 30, "min_samples": 50, "autonomous_margin_min": 0.05, "drift_alert_threshold": 0.1, "drift_sample_size": 50, "baseline_weeks": 4}'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM system_config WHERE key IN ('calibration')
        """
    )
