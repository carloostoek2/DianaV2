"""Add turns.is_sandbox (sandbox isolation for metrics readers).

Revision ID: 037_turns_is_sandbox
Revises: 036_correction_severity
Create Date: 2026-10-19

The sandbox is an in-memory dict (``SandboxService._active``). Write-side
learning paths already skip sandbox chats via ``should_persist``, but metric
readers aggregate ``turns`` / ``pipeline_traces`` which carried no mark. This
column freezes "was the sandbox active for this chat when the turn was
created" so readers can exclude test turns. NOT NULL + server_default false:
historical rows (and rows created after a restart with sandbox on — the
in-memory session is lost) read as real turns. No index: readers already
filter by other indexed columns; the flag is a low-cardinality predicate.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "037_turns_is_sandbox"
down_revision: str | Sequence[str] | None = "036_correction_severity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fail fast instead of queueing behind a long transaction on ``turns``.
    op.execute("SET lock_timeout = '5s'")
    op.add_column(
        "turns",
        sa.Column(
            "is_sandbox",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("turns", "is_sandbox")
