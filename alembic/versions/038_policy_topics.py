"""Doctrinas por tema: policies.temas + gray_zone_queries.topics.

Revision ID: 038_policy_topics
Revises: 037_turns_is_sandbox
Create Date: 2026-10-31

El retrieval semántico de doctrinas (`policies.embedding`, umbral 0.80) solo
acierta cuando el VIP repite casi el mismo mensaje: medido en producción, la
pregunta "¿Crees que algún día se me haga conocerte?" da 0.39 contra la
doctrina guardada (y 0.61 contra el disparador aislado), mientras que mensajes
cariñosos comunes se parecen 0.59–0.62 a cualquier doctrina — bajar el umbral
traería reglas equivocadas.

Las políticas del panel ya se resuelven de forma determinista por tema
(`signals ∩ temas`). Estas dos columnas llevan el mismo mecanismo a las
doctrinas nacidas de la zona gris: al abrir la consulta se guardan los temas
que el Analista asignó al turno, y al guardar la regla viva se copian a
`policies.temas`, de modo que los turnos posteriores con esos temas la
encuentran sin depender del parecido literal.

`topics` en `gray_zone_queries` es el puente entre la consulta (hasta 24 h
abierta) y el resolve. NOT NULL + default '[]': las filas históricas quedan sin
temas y conservan el retrieval por similitud de siempre.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "038_policy_topics"
down_revision: str | Sequence[str] | None = "037_turns_is_sandbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fail fast instead of queueing behind a long transaction on either table.
    op.execute("SET lock_timeout = '5s'")
    op.add_column(
        "policies",
        sa.Column(
            "temas",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "gray_zone_queries",
        sa.Column(
            "topics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    # Igual que en upgrade: DROP COLUMN también pide ACCESS EXCLUSIVE, así que
    # fallar rápido en vez de quedar en cola detrás de una transacción larga.
    op.execute("SET lock_timeout = '5s'")
    op.drop_column("gray_zone_queries", "topics")
    op.drop_column("policies", "temas")
