"""Rename staging_candidates.type → candidate_type.

Migration 003 was edited in place after apply (review fix 7474b02):
ORM/code use candidate_type, but DBs that already ran the original 003 still
have the column named ``type``. This revision aligns live schema.

Idempotent: no-op if candidate_type already exists.

Revision ID: 013_rename_staging_candidate_type
Revises: 012_strip_template_gate_from_forbidden
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "013_rename_staging_candidate_type"
down_revision: Union[str, Sequence[str], None] = "012_strip_template_gate_from_forbidden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'staging_candidates'
                  AND column_name = 'type'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'staging_candidates'
                  AND column_name = 'candidate_type'
            ) THEN
                ALTER TABLE staging_candidates RENAME COLUMN type TO candidate_type;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'staging_candidates'
                  AND column_name = 'candidate_type'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'staging_candidates'
                  AND column_name = 'type'
            ) THEN
                ALTER TABLE staging_candidates RENAME COLUMN candidate_type TO type;
            END IF;
        END $$;
        """
    )
