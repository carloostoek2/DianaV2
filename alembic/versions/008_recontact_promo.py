"""recontact_schedules + promo_triggers/executions + seeds (Pool 2 schema)

Revision ID: 008_recontact_promo
Revises: 007_vip_auto_send
Create Date: 2026-07-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "008_recontact_promo"
down_revision: Union[str, Sequence[str], None] = "007_vip_auto_send"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- recontact_schedules --
    op.create_table(
        "recontact_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["vip_id"], ["vips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recontact_schedules_next_status "
        "ON recontact_schedules (next_contact_at, status)"
    )

    # -- promo_triggers --
    op.create_table(
        "promo_triggers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("trigger_text", sa.Text(), nullable=False),
        sa.Column(
            "response_sequence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("repeat_first_message", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trigger_text"),
    )

    # -- promo_executions --
    op.create_table(
        "promo_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "sequence_sent",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'sent'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trigger_id"], ["promo_triggers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promo_executions_chat_trigger_sent "
        "ON promo_executions (chat_id, trigger_id, sent_at DESC)"
    )

    # -- system_config seeds (recontact + promo blobs only; FEATURE_* owned by 006) --
    op.execute(
        """
        INSERT INTO system_config (key, value) VALUES
        ('recontact',
         '{"inactivity_days": 7, "templates": ["Hola {nombre}, ¿cómo andás? Hace un tiempo que no hablamos y quería saber cómo estás 😊", "Holis {nombre}! Me acordé de vos y quería saber si necesitabas algo de mi parte 💕"]}'::jsonb),
        ('promo',
         '{"repeat_days": 30}'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )

    # -- promo_triggers seed rows (feminine first-person Spanish) --
    op.execute(
        """
        INSERT INTO promo_triggers (trigger_text, response_sequence, repeat_first_message, is_active)
        VALUES
        (
          'quiero información',
          '["Hola! Te cuento mis promos de esta semana 😊", "Tengo opciones pensadas para vos y las armo a tu ritmo.", "Si te copa, escribime y lo vemos juntas 💕"]'::jsonb,
          'Holis 😁 claro, te mando de nuevo mis promos...',
          true
        ),
        (
          'promociones',
          '["Hola! Acá te dejo mis promociones vigentes ✨", "Las armé pensando en lo que más piden y las adapto a vos.", "Cualquier duda, escribime y te ayudo con gusto 💕"]'::jsonb,
          'Holis de nuevo 😊 te reenvío mis promociones por si no las viste...',
          true
        )
        """
    )


def downgrade() -> None:
    op.drop_table("promo_executions")
    op.drop_table("promo_triggers")
    op.drop_table("recontact_schedules")
    op.execute(
        """
        DELETE FROM system_config WHERE key IN ('recontact', 'promo')
        """
    )
