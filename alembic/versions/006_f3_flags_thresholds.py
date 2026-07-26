"""Seed F3 feature flags (false) + dual eval thresholds (SPEC §4.2).

Revision ID: 006_f3_flags_thresholds
Revises: 005_trace_timings
Create Date: 2026-07-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_f3_flags_thresholds"
down_revision: Union[str, Sequence[str], None] = "005_trace_timings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # alembic_version.version_num defaults to VARCHAR(32); widen for safety.
    op.execute(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"
    )
    op.execute(
        """
        INSERT INTO system_config (key, value) VALUES
        ('FEATURE_AUTONOMOUS_MODE', 'false'::jsonb),
        ('FEATURE_RECONTACT_ENABLED', 'false'::jsonb),
        ('FEATURE_PROMO_ENABLED', 'false'::jsonb),
        ('FEATURE_CALIBRATION_ENABLED', 'false'::jsonb),
        ('FEATURE_ADVANCED_BEHAVIOR', 'false'::jsonb),
        ('autonomous_thresholds',
         '{"safety_min": 0.9, "doctrine_min": 0.8, "naturalness_min": 0.7}'::jsonb),
        ('supervised_thresholds',
         '{"safety_min": 0.5, "doctrine_min": 0.4, "naturalness_min": 0.5}'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    # Delete only keys this revision inserted (safe re-run / reverse).
    op.execute(
        """
        DELETE FROM system_config WHERE key IN (
          'FEATURE_AUTONOMOUS_MODE',
          'FEATURE_RECONTACT_ENABLED',
          'FEATURE_PROMO_ENABLED',
          'FEATURE_CALIBRATION_ENABLED',
          'FEATURE_ADVANCED_BEHAVIOR',
          'autonomous_thresholds',
          'supervised_thresholds'
        )
        """
    )
