"""Latido del vigilante de contratos — el archivo que dice "corri y esto encontre".

Por que un archivo y no la base: el chequeo diario es **solo lectura sobre la base**, asi que
no puede guardar su propio estado ahi. El latido vive en ``runtime/contract_watchdog.json`` y
lo leen dos consumidores:

* el propio job, para no repetir la corrida del dia cuando el bot se reinicia;
* ``/health``, para que un vigilante que dejo de correr **se vea**, en vez de parecerse a un
  vigilante tranquilo.

La foto de los fallos internos del proceso tambien viaja aqui: es lo que permite que el aviso
de la corrida siguiente diga que crecio **desde el chequeo anterior** y no el acumulado desde
que arranco el bot.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("diana.application")

#: Ubicacion por defecto del latido (junto al log del resto de los jobs).
HEARTBEAT_PATH = Path(__file__).resolve().parents[3] / "runtime" / "contract_watchdog.json"

#: Un latido mas viejo que esto se considera vencido en ``/health``. El chequeo es diario;
#: 36 h deja margen para un reinicio sin que el hueco pase por "todo bien".
STALE_AFTER_HOURS = 36

#: Versión del formato del latido (para poder cambiarlo sin romper a quien lo lea).
FORMAT_VERSION = 1


def read_heartbeat(path: Path | None = None) -> dict[str, Any] | None:
    """Lee el latido. Archivo ausente o ilegible → ``None`` (nunca levanta)."""
    ruta = path or HEARTBEAT_PATH
    try:
        crudo = ruta.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("contract_watchdog_heartbeat_unreadable", extra={"error": str(exc)})
        return None
    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError as exc:
        logger.warning("contract_watchdog_heartbeat_corrupt", extra={"error": str(exc)})
        return None
    return datos if isinstance(datos, dict) else None


def write_heartbeat(payload: dict[str, Any], path: Path | None = None) -> None:
    """Escribe el latido de forma atomica (temporal + reemplazo).

    Levanta si no puede escribir: quien llama decide como reportarlo (el job lo registra y
    sigue). Un latido a medias seria peor que ninguno.
    """
    ruta = path or HEARTBEAT_PATH
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cuerpo = {**payload, "format_version": FORMAT_VERSION}
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=ruta.parent, prefix=ruta.name, suffix=".tmp", delete=False
    ) as temporal:
        json.dump(cuerpo, temporal, ensure_ascii=False, indent=2, default=str)
        temporal.write("\n")
        nombre_temporal = temporal.name
    os.replace(nombre_temporal, ruta)


def seconds_since(iso_timestamp: Any, *, now: datetime | None = None) -> int | None:
    """Segundos transcurridos desde una marca ISO del latido. ``None`` si no se puede leer."""
    if not isinstance(iso_timestamp, str) or not iso_timestamp:
        return None
    try:
        momento = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    referencia = now or datetime.now(UTC)
    return max(0, int((referencia - momento).total_seconds()))


def summarize_heartbeat(
    payload: dict[str, Any] | None,
    *,
    enabled: bool,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Bloque ``watchdog`` de ``/health``. ``None`` cuando no hay nada que mostrar.

    Con la bandera apagada y sin latido previo no se muestra nada: ``/health`` responde igual
    que antes de que existiera el vigilante.
    """
    if payload is None:
        if not enabled:
            return None
        return {
            "ok": True,
            "enabled": True,
            "last_run_at": None,
            "age_seconds": None,
            "result": "sin_corrida",
            "alerts": 0,
        }

    edad = seconds_since(payload.get("last_run_at"), now=now)
    resultado = str(payload.get("result") or "desconocido")
    vencido = edad is None or edad > STALE_AFTER_HOURS * 3600
    return {
        "ok": resultado != "fallo" and not vencido,
        "enabled": enabled,
        "last_run_at": payload.get("last_run_at"),
        "age_seconds": edad,
        "result": resultado,
        "alerts": int(payload.get("alerts") or 0),
    }


__all__ = [
    "FORMAT_VERSION",
    "HEARTBEAT_PATH",
    "STALE_AFTER_HOURS",
    "read_heartbeat",
    "seconds_since",
    "summarize_heartbeat",
    "write_heartbeat",
]
