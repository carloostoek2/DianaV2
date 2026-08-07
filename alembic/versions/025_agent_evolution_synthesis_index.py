"""agent_evolution_synthesis_index: index feeding the profile-synthesis cycle (Fase 1)

Revision ID: 025_agent_evolution_synthesis_index
Revises: 024_agent_evolution_foundations
Create Date: 2026-08-07

Implements SPEC-EVOLUCION-AGENTE v1.2 §Fase 1 (impact decision D1): the
profile-synthesis cycle counts "messages since last synthesis" and "last
activity" over ``turns`` (vip_id + created_at + channel_type='vip') — a
message is one turn, and an edit never creates a new turn. The new index
``ix_turns_vip_id_created_at`` feeds both ``SqlTurnStore.count_messages_since``
and the group-by of ``SqlTurnStore.list_vips_with_activity_older_than``.

Non-unique and deliberately narrow (vip_id + created_at only): ``channel_type``
is filtered in the WHERE clause, not indexed. ``pipeline_traces`` (TTL 30d)
and ``message_history`` (chat-scoped, no vip_id) were rejected as the activity
source (A2).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "025_agent_evolution_synthesis_index"
down_revision: str | Sequence[str] | None = "024_agent_evolution_foundations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_turns_vip_id_created_at",
        "turns",
        ["vip_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_turns_vip_id_created_at", table_name="turns")
