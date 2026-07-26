"""Index pipeline_traces by chat_id + created_at DESC for recent intents.

Revision ID: 011_pipeline_traces_chat_intents_idx
Revises: 010_owner_marks
Create Date: 2026-07-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_pipeline_traces_chat_intents_idx"
down_revision: Union[str, Sequence[str], None] = "010_owner_marks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_pipeline_traces_chat_id_created_at",
            "pipeline_traces",
            ["chat_id", sa.text("created_at DESC")],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_pipeline_traces_chat_id_created_at",
            table_name="pipeline_traces",
            postgresql_concurrently=True,
            if_exists=True,
        )
