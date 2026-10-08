#!/usr/bin/env python3
"""Modo seco del vigilante de contratos — que avisaria hoy, sin mandar nada.

El chequeo de verdad corre **dentro del bot** (``diana.jobs.contract_watchdog``), que es lo que
le permite leer los contadores de fallos internos del proceso y publicar su latido en
``/health``. Este script existe para mirarlo a mano contra la base real sin esperar la corrida
del dia, y usa **el mismo servicio**, asi que lo que muestra es exactamente lo que avisaria.

Solo lectura: no manda mensajes, no escribe el latido y no toca la base.

Uso::

    venv/bin/python scripts/vigilantes.py            # muestra el aviso tal como saldria
    venv/bin/python scripts/vigilantes.py --json     # resultado crudo de cada vigilante
    venv/bin/python scripts/vigilantes.py --avisar-activacion   # aviso de puesta en marcha (una vez)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from diana.application.contract_watchdog_service import ContractWatchdogService  # noqa: E402
from diana.infrastructure.journal_sandbox_turns import JournalSandboxTurnClassifier  # noqa: E402

#: Aviso de puesta en marcha: se manda UNA vez, a mano, cuando la vigilancia se activa o se
#: reinstala (por ejemplo, al cambiar de cuenta o de maquina). No es parte de la corrida
#: diaria: el dia a dia solo escribe si algo dejo de funcionar.
AVISO_ACTIVACION = (
    "✅ Vigilancia diaria activada\n"
    "\n"
    "Desde hoy reviso sola, una vez por dia, cuatro cosas, y te escribo SOLO si algo dejo de "
    "funcionar:\n"
    "• que lo que Diana guarda no quede con la huella vacia (el problema de agosto);\n"
    "• que cada intercambio con un VIP siga dejando el registro de lo que Diana habria "
    "decidido sola;\n"
    "• que no quede una escalacion sin que la hayas podido resolver;\n"
    "• que lo que apruebas o corriges quede guardado (el defecto de septiembre).\n"
    "\n"
    "Si no hay novedades, no te escribo: el silencio significa que esta todo en orden.\n"
    'Probe la alarma a proposito y suena (incluida la de "no pude revisar").'
)


def _env(clave: str) -> str:
    """Lee una clave del .env real (mismo criterio que el resto de scripts/)."""
    for linea in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave_leida, _, valor = linea.partition("=")
        if clave_leida.strip() == clave:
            return valor.strip().strip('"').strip("'")
    raise KeyError(f"{clave} no esta en el .env")


def _database_url() -> str:
    return _env("DATABASE_URL")


def _avisar(texto: str, *, dry_run: bool) -> None:
    """Manda el texto a la duena por la Bot API. ``dry_run`` solo lo muestra."""
    if dry_run:
        print("--- mensaje que se mandaria ---")
        print(texto)
        print("--- (modo seco: no se mando nada) ---")
        return
    datos = json.dumps({"chat_id": _env("OWNER_TELEGRAM_ID"), "text": texto}).encode()
    peticion = urllib.request.Request(
        f"https://api.telegram.org/bot{_env('TELEGRAM_BOT_TOKEN')}/sendMessage",
        data=datos,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:  # noqa: S310
        if respuesta.status != 200:
            raise RuntimeError(f"Telegram respondio {respuesta.status}")


async def _correr(como_json: bool) -> int:
    engine = create_async_engine(_database_url())
    try:
        service = ContractWatchdogService(
            async_sessionmaker(engine, expire_on_commit=False),
            sandbox_turns=JournalSandboxTurnClassifier(),
        )
        report = await service.revisar()
        if como_json:
            print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False, default=str))
        mensaje = service.componer_mensaje(report)
        if mensaje is None:
            print(f"todo en orden — 0 alertas (sandbox descartados: {report.skipped_sandbox})")
            return 0
        print("--- mensaje que se mandaria ---")
        print(mensaje)
        print("--- (modo seco: no se mando nada) ---")
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="resultado crudo de cada vigilante")
    parser.add_argument(
        "--avisar-activacion",
        action="store_true",
        help="manda el aviso de puesta en marcha (una vez, al activar la vigilancia)",
    )
    parser.add_argument("--dry-run", action="store_true", help="muestra el mensaje sin mandarlo")
    argumentos = parser.parse_args()
    if argumentos.avisar_activacion:
        _avisar(AVISO_ACTIVACION, dry_run=argumentos.dry_run)
        print("aviso de activacion: " + ("dry-run" if argumentos.dry_run else "enviado"))
        return
    sys.exit(asyncio.run(_correr(argumentos.json)))


if __name__ == "__main__":
    main()
