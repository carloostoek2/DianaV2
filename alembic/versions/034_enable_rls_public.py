"""Enable Row-Level Security on all user tables in the public schema.

Revision ID: 034_enable_rls_public
Revises: 033_gray_zone_proposal
Create Date: 2026-08-25

Supabase linter 0013_rls_disabled_in_public flags every public table exposed to
PostgREST that has RLS disabled. The Diana backend connects to Postgres with the
superuser role (bypasses RLS), so enabling RLS does NOT affect application
behaviour. It closes the exposure surface of the Supabase Data API (anon /
authenticated roles), where a leaked anon key would otherwise allow reading or
writing these tables via REST. No policies are created here: with RLS on and no
policy, non-owner roles are denied; the app's superuser connection is unaffected.

Tables are enumerated at runtime from pg_tables so the migration is complete
over the current schema and stays idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "034_enable_rls_public"
down_revision: str | Sequence[str] | None = "033_gray_zone_proposal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PUBLIC_TABLES = sa.text(
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
)
_ENABLE = 'ALTER TABLE "public"."{table}" ENABLE ROW LEVEL SECURITY'
_DISABLE = 'ALTER TABLE "public"."{table}" DISABLE ROW LEVEL SECURITY'


def upgrade() -> None:
    conn = op.get_bind()
    tables = conn.execute(_PUBLIC_TABLES).scalars().all()
    for table in tables:
        conn.execute(sa.text(_ENABLE.format(table=table)))


def downgrade() -> None:
    conn = op.get_bind()
    tables = conn.execute(_PUBLIC_TABLES).scalars().all()
    for table in tables:
        conn.execute(sa.text(_DISABLE.format(table=table)))
