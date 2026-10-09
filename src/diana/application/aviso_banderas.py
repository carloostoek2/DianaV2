"""Aviso de arranque por banderas nucleo apagadas.

Cada vez que el bot arranca deja **un solo** resumen en el registro: que banderas nucleo estan
apagadas, con motivo y fecha las que se apagaron a proposito, y aparte las que estan apagadas sin
declarar. El mismo resumen queda publicado en ``/health`` (``checks.banderas``) y, si hay algo que
revisar, la dueña recibe **un** mensaje por Telegram.

Tres invariantes:

* **Nunca frena el arranque.** Un aviso, no un bloqueo: si algo falla aca, se registra y el bot
  arranca igual.
* **El registro sale siempre.** Es la foto del arranque y sirve de comprobante de que el chequeo
  corrio; lo que no se repite es el mensaje a la dueña.
* **El mensaje no se repite.** Se guarda la huella de la advertencia y solo se vuelve a avisar si
  cambio (misma idea que el latido del vigilante de contratos).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from diana.config.banderas_nucleo import EstadoBanderas, estado_banderas
from diana.config.settings import Settings

logger = logging.getLogger("diana.application")

#: Estado del ultimo arranque (junto al latido del vigilante y al log de los jobs).
STATE_PATH = Path(__file__).resolve().parents[3] / "runtime" / "banderas_arranque.json"

#: Version del formato del estado, para poder cambiarlo sin romper a quien lo lea.
STATE_FORMAT_VERSION = 1

#: Ruta del archivo de entorno, la misma que lee ``Settings`` (relativa al directorio de trabajo).
ENV_PATH = Path(".env")


def leer_variables_feature(path: Path | None = None) -> frozenset[str]:
    """Nombres de variable ``FEATURE_*`` activos en el archivo de entorno.

    Las lineas comentadas no cuentan: solo lo que el proceso realmente lee. Un archivo ausente o
    ilegible devuelve el conjunto vacio (no hay nada que reportar, no es un error del arranque).
    """
    ruta = path or ENV_PATH
    try:
        crudo = ruta.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return frozenset()
    nombres: set[str] = set()
    for linea in crudo.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        if limpia.startswith("export "):
            limpia = limpia[len("export ") :].lstrip()
        clave, separador, _ = limpia.partition("=")
        if not separador:
            continue
        clave = clave.strip()
        if clave.startswith("FEATURE_"):
            nombres.add(clave)
    return frozenset(nombres)


def valores_de_settings(settings: Settings) -> dict[str, bool]:
    """Valor efectivo de cada campo ``feature_*`` de ``Settings``."""
    return {
        nombre: bool(getattr(settings, nombre, False))
        for nombre in type(settings).model_fields
        if nombre.startswith("feature_")
    }


def leer_estado(path: Path | None = None) -> dict[str, Any] | None:
    """Estado del arranque anterior. Ausente o ilegible → ``None`` (nunca levanta)."""
    ruta = path or STATE_PATH
    try:
        crudo = ruta.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError:
        logger.warning("banderas_arranque_estado_corrupto")
        return None
    return datos if isinstance(datos, dict) else None


def escribir_estado(payload: dict[str, Any], path: Path | None = None) -> None:
    """Escribe el estado de forma atomica (temporal + reemplazo)."""
    ruta = path or STATE_PATH
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    descriptor, temporal = tempfile.mkstemp(dir=str(ruta.parent), prefix=".banderas-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as manejador:
            manejador.write(contenido)
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def leer_bloque_banderas(path: Path | None = None) -> dict[str, Any] | None:
    """Bloque para ``/health``: el resumen tal como quedo en el ultimo arranque.

    Se lee del archivo (y no de memoria del proceso) para que un consumidor externo vea lo mismo
    que quedo registrado, aunque el bot se haya reiniciado.
    """
    estado = leer_estado(path)
    if estado is None:
        return None
    bloque = estado.get("health")
    return bloque if isinstance(bloque, dict) else None


def _debe_avisar(estado: EstadoBanderas, anterior: dict[str, Any] | None) -> bool:
    """Solo se avisa si hay advertencia y cambio respecto del arranque anterior.

    Estado ausente o ilegible → se avisa (mejor de mas que de menos: es un aviso de gobierno).
    """
    if not estado.hay_advertencia:
        return False
    if anterior is None:
        return True
    return anterior.get("huella") != estado.huella_advertencia()


def _bloque_de_registro(estado: EstadoBanderas) -> str:
    """El resumen del registro: con detalle si hay algo que contar, corto si no hay nada."""
    if not estado.hay_algo_que_contar:
        return estado.resumen_corto()
    if estado.hay_advertencia:
        encabezado = "Banderas nucleo que conviene revisar (aviso, no bloqueo):"
    else:
        encabezado = "Banderas nucleo apagadas a proposito al arrancar (aviso, no bloqueo):"
    return "\n".join([encabezado, *estado.bloque_legible()])


async def avisar_banderas_nucleo(
    app: Any,
    *,
    env_path: Path | None = None,
    state_path: Path | None = None,
) -> EstadoBanderas | None:
    """Deja el resumen en el registro, lo publica y avisa a la dueña si hace falta.

    Devuelve el estado calculado, o ``None`` si algo fallo (el arranque sigue igual).
    """
    try:
        settings: Settings = app.settings
        estado = estado_banderas(
            valores_de_settings(settings),
            leer_variables_feature(env_path),
        )
        anterior = leer_estado(state_path)
        avisar = _debe_avisar(estado, anterior)

        mensaje = _bloque_de_registro(estado)
        if estado.hay_advertencia:
            logger.warning(mensaje, extra=estado.para_registro())
        else:
            logger.info(mensaje, extra=estado.para_registro())

        try:
            escribir_estado(
                {
                    "format_version": STATE_FORMAT_VERSION,
                    "huella": estado.huella_advertencia(),
                    "health": estado.para_health(),
                },
                state_path,
            )
        except OSError:
            logger.exception("banderas_arranque_estado_no_escrito")

        if avisar:
            try:
                await app.notifier.notify_info(estado.mensaje_aviso() or "")
            except Exception:
                logger.exception("banderas_arranque_aviso_no_enviado")
        return estado
    except Exception:
        # Morir callado es peor que no avisar: se registra y el arranque continua.
        logger.exception("banderas_arranque_fallo")
        return None


__all__ = [
    "ENV_PATH",
    "STATE_FORMAT_VERSION",
    "STATE_PATH",
    "avisar_banderas_nucleo",
    "escribir_estado",
    "leer_bloque_banderas",
    "leer_estado",
    "leer_variables_feature",
    "valores_de_settings",
]
