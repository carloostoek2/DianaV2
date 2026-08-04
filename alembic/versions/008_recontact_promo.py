"""recontact_schedules + promo_triggers/executions + seeds (Pool 2 schema)

Revision ID: 008_recontact_promo
Revises: 007_vip_auto_send
Create Date: 2026-07-26
"""

from __future__ import annotations

import json
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
         '{"inactivity_days": 7, "templates": ["Hola {nombre}, ¿cómo estás? Hace un tiempo que no hablamos y quería saber cómo te va 😊", "Holis {nombre}! Me acordé de ti y quería saber si necesitas algo de mi parte 💕"]}'::jsonb),
        ('promo',
         '{"repeat_days": 30}'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )

    # -- promo_triggers seed rows (natural Spanish) --
    _promo_msj1 = "Holaaa 💕\nTe mando mis promos 🔥"
    _promo_repeat = "Holis 😁\nClaro te mando de nuevo mis promos 🔥"
    _promo_msj2 = (
        "<b>Precios en pesos mexicanos</b>\n"
        "\n"
        "♥ <b>Encanto Inicial</b> 💫 - Explora mi lado más coqu3to con 1 video y 10 fotos, una dulce introducción para conocernos mejor.\n"
        "📸 <b>Precio $150</b> (10 usd)\n"
        "1 video donde me toco, juego con mis labios y 🍒\n"
        "10 fotos semid3snuda o con lencería\n"
        "\n"
        "🔴 <b>Sensualidad Revelada</b> 🔥 - Déjate seducir con 2 videos y 10 fotos, donde desvelo mi lado más atrevido.\n"
        "🎥 <b>Precio: $200</b> (14 usd)\n"
        "2 videos donde me toc@, me abro bien ric@ me +turbo y se ve mi cara más 10 fotos\n"
        "\n"
        "❤️‍🔥 <b>Pasión Desbordante</b> 💋 - Vive la intensidad con 3 videos y 15 fotos, una experiencia íntima llena de emociones.\n"
        "🎬 <b>Precio: $250</b> (17 usd)\n"
        "Tres videos, uno con lencería muy s3nsual otro vestida y jugando muy s3xy y el último jugando con un dild0 🍒 me toco 🍑 más 15 fotos\n"
        "\n"
        "❤️ <b>Intimidad Explosiva</b> 🔞 - Sumérgete en mí con 5 videos y 15 fotos, contenido totalmente atrevido y explícit0\n"
        "🎞️ <b>Precio: $300</b> (20 usd)\n"
        "Set de 5 videos totalmente explícit0s tocándome hasta terminar 💦, jugando con dildo, desvistiéndome hasta quedar d3snud@, usando juguetitos y uno exclusivo c0gi3ndo montando y moviendome rico 😈 más 15 fotos de obsequio\n"
        "\n"
        "💎 EL DIVÁN VIP 💎\n"
        "<s>Recibe antes que nadie lo más nuevo y ric0 de mi cont3nid0 suscribiéndote a mi canal privado y exclusivo y déjate consentir por la señorita más K1nky 🔥\n"
        "<b>Subscripción mensual de $350 (23 usd)</b></s>"
    )
    _promo_seq = json.dumps([_promo_msj1, _promo_msj2], ensure_ascii=False)
    _promociones_seq = json.dumps(
        [
            "Hola! Acá te dejo mis promociones vigentes ✨",
            "Las armé pensando en lo que más piden y las adapto a ti.",
            "Cualquier duda, escríbeme y te ayudo con gusto 💕",
        ],
        ensure_ascii=False,
    )
    op.execute(
        "INSERT INTO promo_triggers "
        "(trigger_text, response_sequence, repeat_first_message, is_active) VALUES "
        f"('Quiero más información 🔥', '{_promo_seq}'::jsonb, '{_promo_repeat}', true), "
        f"('promociones', '{_promociones_seq}'::jsonb, "
        "'Holis de nuevo 😊 te reenvío mis promociones por si no las viste...', false)"
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
