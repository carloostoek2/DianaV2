#!/usr/bin/env python3
"""Cierra las ventanas de atencion (30 días) abiertas por la convocatoria de
reintegración VIP ("Hey, yo soy VIP!").

Por qué existe: cuando un chat no-VIP escribe la frase exacta del trigger, el
bot entrega los 3 mensajes de la promo y, como cualquier promo, abre su ventana
de atencion de 30 días (`atencion_cycles`). Durante la jornada de la
convocatoria eso dejaría a esos chats en modo general/atencion (el bot les
respondería consumiendo tokens que no les corresponden). Este script cierra esa
ventana apenas aparece, para que el sistema deje de tratarlos como atencion.

Cómo se usa (idempotente, puede correrse cada N minutos/hora durante el día):
    cd /home/ubuntu/repos/DianaV2
    venv/bin/python scripts/close_reintegration_atencion_windows.py

Solo actúa sobre:
  - chats que ejecutaron (status='sent') el trigger "Hey, yo soy VIP!"
  - y que tengan una fila en atencion_cycles con closed_at IS NULL.

Cierra marcando closed_at + close_reason (no borra): al quedar la fila cerrada,
si el mismo chat vuelve a escribir la frase el promo no reabre la ventana
(start_if_absent hace ON CONFLICT DO NOTHING sobre chat_id).

Conexión: lee DATABASE_URL desde el .env de DianaV2. Solo escritura mínima.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

TRIGGER_TEXT = "Hey, yo soy VIP!"
CLOSE_REASON = "reintegracion_vip"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _database_url() -> str:
    raw = None
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == "DATABASE_URL":
            raw = v.strip().strip('"').strip("'")
            break
    if not raw:
        raise SystemExit("DATABASE_URL no está en .env")
    if raw.startswith("postgres://") and "+" not in raw.split("://")[0]:
        return raw.replace("postgres://", "postgresql+asyncpg://", 1)
    if raw.startswith("postgresql://") and "postgresql+" not in raw:
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


async def _main() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_database_url())
    try:
        async with engine.begin() as conn:
            trigger_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM promo_triggers "
                        "WHERE trigger_text = :tt AND is_active"
                    ),
                    {"tt": TRIGGER_TEXT},
                )
            ).scalar_one_or_none()
            if trigger_id is None:
                print(f"trigger '{TRIGGER_TEXT}' no encontrado; nada que hacer.")
                return

            # chats que recibieron la promo (sent) de este trigger
            rows = (
                await conn.execute(
                    text(
                        "SELECT DISTINCT chat_id FROM promo_executions "
                        "WHERE trigger_id = :tid AND status = 'sent'"
                    ),
                    {"tid": trigger_id},
                )
            ).scalars().all()
            if not rows:
                print("sin ejecuciones 'sent' del trigger; nada que hacer.")
                return

            result = await conn.execute(
                text(
                    "UPDATE atencion_cycles "
                    "SET closed_at = now(), close_reason = :reason "
                    "WHERE chat_id = ANY(:ids) AND closed_at IS NULL"
                ),
                {"reason": CLOSE_REASON, "ids": list(rows)},
            )
            n = result.rowcount
        print(f"ventanas cerradas ahora: {n}")
        print(f"(chats considerados del trigger: {len(rows)})")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
