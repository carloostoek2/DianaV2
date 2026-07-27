"""Strip TemplateGate annex phrases from forbidden_keywords.

Legacy seed included ``eres un bot``, which after H6 would silent-escalate
before CognitiveDirector TemplateGate. Remove known annex deteccion_ia phrases
from the JSON array if present; keep real forbidden words.

Revision ID: 012_strip_template_gate_from_forbidden
Revises: 011_pipeline_traces_chat_intents_idx
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "012_strip_template_gate_from_forbidden"
down_revision: Union[str, Sequence[str], None] = "011_pipeline_traces_chat_intents_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirror TEMPLATE_GATE_OWNED_FORBIDDEN_PHRASES (forbidden.py) for DB cleanup.
_OWNED = (
    "eres una ia",
    "eres un bot",
    "eres ia",
    "hablo con una ia",
    "hablo con un bot",
    "eres real",
)


def upgrade() -> None:
    owned_sql = ", ".join(f"'{p}'" for p in _OWNED)
    op.execute(
        f"""
        UPDATE system_config
        SET value = (
            SELECT COALESCE(jsonb_agg(to_jsonb(elem)), '[]'::jsonb)
            FROM jsonb_array_elements_text(value) AS t(elem)
            WHERE lower(elem) NOT IN ({owned_sql})
        ),
        updated_at = now()
        WHERE key = 'forbidden_keywords'
          AND jsonb_typeof(value) = 'array'
        """
    )


def downgrade() -> None:
    # Re-add legacy seed phrase only if missing (best-effort; not identity-preserving).
    op.execute(
        """
        UPDATE system_config
        SET value = value || '["eres un bot"]'::jsonb,
            updated_at = now()
        WHERE key = 'forbidden_keywords'
          AND jsonb_typeof(value) = 'array'
          AND NOT (value @> '"eres un bot"'::jsonb)
        """
    )
