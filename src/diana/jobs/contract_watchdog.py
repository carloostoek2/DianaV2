"""ContractWatchdogJob — chequeo diario de que los efectos prometidos siguen ocurriendo.

Una prueba en verde dice que el efecto ocurria **el dia que se midio**. Este job es el que
avisa si manana deja de ocurrir. Corre dentro del bot, y eso no es un detalle de
implementacion: es lo que le permite leer los contadores de fallos internos del proceso (el
unico lugar donde existen) y publicar su latido para que ``/health`` lo muestre.

Como se planifica:

* una corrida cada ``interval_seconds`` (24 h), pero **nunca antes** de
  ``min_hours_between_runs`` horas desde la ultima, segun el latido;
* al arrancar el bot, si el latido ya tiene esas horas encima, corre de inmediato — asi un
  reinicio no adelanta la corrida del dia ni la pierde;
* el aviso va a la duena **solo si algo falla**; si esta todo bien, no manda nada.

Tres cosas que este job no hace: no escribe en la base (el chequeo es solo lectura), no
propaga excepciones (un job nunca tumba al bot) y no se calla cuando falla — una corrida rota
manda mensaje y queda en el latido.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from diana.application.contract_watchdog_service import (
    ContractWatchdogService,
    WatchdogReport,
    claves_avisadas,
    filtrar_ya_avisados,
)
from diana.application.observability import get_swallowed_counts
from diana.application.watchdog_heartbeat import (
    HEARTBEAT_PATH,
    read_heartbeat,
    seconds_since,
    write_heartbeat,
)

logger = logging.getLogger("diana.jobs")

#: Intervalo entre corridas (diario).
DEFAULT_INTERVAL_SECONDS = 86400

#: Minimo entre dos corridas. Mas bajo que 24 h a proposito: un reinicio no tiene que adelantar
#: el chequeo del dia, pero tampoco correrlo 24 h despues de cada reinicio.
MIN_HOURS_BETWEEN_RUNS = 20

#: Piso de la espera entre iteraciones. Sin el, un latido que no se puede escribir dejaria el
#: bucle girando sin descanso contra la base.
MIN_WAIT_SECONDS = 900

#: Si el notifier no esta cableado, el aviso solo se registra; el latido lo delata.
_NO_NOTIFIER = "contract_watchdog_no_notifier"


def _delta_swallowed(
    actuales: Mapping[str, int], previos: Any
) -> dict[str, int]:
    """Cuanto crecio cada fallo interno desde el chequeo anterior.

    La primera corrida de un proceso no tiene con que comparar (los contadores arrancan en
    cero con el proceso), asi que reporta el total y no inventa un delta.
    """
    if not isinstance(previos, Mapping):
        return {evento: int(cuantos) for evento, cuantos in actuales.items()}
    return {
        evento: int(cuantos) - int(previos.get(evento, 0) or 0)
        for evento, cuantos in actuales.items()
    }


async def _avisar(notifier: Any | None, texto: str) -> None:
    """Manda el aviso a la duena. Un fallo de Telegram no puede romper la corrida."""
    if notifier is None:
        logger.warning(_NO_NOTIFIER, extra={"aviso": texto[:200]})
        return
    try:
        await notifier.notify_info(texto)
        logger.info("contract_watchdog_notified", extra={"chars": len(texto)})
    except Exception:
        logger.exception("contract_watchdog_notify_failed")


async def run_contract_watchdog_cycle(
    service: ContractWatchdogService,
    *,
    heartbeat_path: Path | None = None,
    notifier: Any | None = None,
    swallowed_counts: Callable[[], Mapping[str, int]] = get_swallowed_counts,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Una corrida completa: revisa, avisa si hace falta y deja el latido. Nunca propaga."""
    ruta = heartbeat_path or HEARTBEAT_PATH
    momento = (now or (lambda: datetime.now(UTC)))()
    anterior = read_heartbeat(ruta) or {}

    actuales = dict(swallowed_counts())
    delta = _delta_swallowed(actuales, anterior.get("swallowed"))

    report = WatchdogReport()
    try:
        report = await service.revisar()
        report = filtrar_ya_avisados(report, anterior.get("alerted") or [])
        mensaje = service.componer_mensaje(report, swallowed_delta=delta)
        if mensaje:
            await _avisar(notifier, mensaje)
        resultado = "ok" if report.ok else "alertas"
    except Exception as exc:  # noqa: BLE001 — morir callado es el peor resultado
        # Una falla del propio vigilante no puede parecerse a un vigilante tranquilo.
        logger.exception("contract_watchdog_run_error")
        resultado = "fallo"
        await _avisar(
            notifier,
            f"⚠️ La vigilancia de Diana no pudo correr: {type(exc).__name__}: {exc}",
        )

    latido = {
        "last_run_at": momento.isoformat(),
        "result": resultado,
        "alerts": sum(len(alerta.rows) for alerta in report.alerts),
        "failures": len(report.failures),
        "skipped_sandbox": report.skipped_sandbox,
        "alerted": claves_avisadas(report),
        "swallowed": actuales,
    }
    try:
        write_heartbeat(latido, ruta)
    except Exception:
        logger.exception("contract_watchdog_heartbeat_write_failed")

    logger.info(
        "contract_watchdog_run_complete",
        extra={"result": resultado, "alerts": latido["alerts"], "failures": latido["failures"]},
    )
    return latido


class ContractWatchdogJob:
    """Corre el chequeo de contratos una vez por dia mientras el bot este vivo.

    ``start()`` es de una sola vez: despues de ``stop()`` hay que crear otra instancia.
    """

    def __init__(
        self,
        service: ContractWatchdogService,
        *,
        notifier: Any | None = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        heartbeat_path: Path | None = None,
        min_hours_between_runs: int = MIN_HOURS_BETWEEN_RUNS,
        now: Callable[[], datetime] | None = None,
        swallowed_counts: Callable[[], Mapping[str, int]] = get_swallowed_counts,
    ) -> None:
        self._service = service
        self._notifier = notifier
        self._interval = interval_seconds
        self._heartbeat_path = heartbeat_path or HEARTBEAT_PATH
        self._min_hours = min_hours_between_runs
        self._now = now or (lambda: datetime.now(UTC))
        self._swallowed_counts = swallowed_counts
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Corre el bucle del vigilante hasta que se llame a ``stop()``."""
        logger.info(
            "contract_watchdog_job_started",
            extra={
                "interval_seconds": self._interval,
                "min_hours_between_runs": self._min_hours,
            },
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                resultado = await asyncio.wait_for(
                    self._correr_si_toca(),
                    timeout=self._interval,
                )
                logger.info(
                    "contract_watchdog_job_tick",
                    extra={**resultado, "duration_ms": int((time.monotonic() - t0) * 1000)},
                )
            except TimeoutError:
                logger.warning("contract_watchdog_run_timeout")
            except Exception:
                logger.exception("contract_watchdog_run_error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._segundos_hasta_la_proxima(),
                )
                break  # stop event was set during the timeout
            except TimeoutError:
                continue  # normal interval elapsed

        logger.info("contract_watchdog_job_stopped")

    async def stop(self) -> None:
        """Senala al bucle que pare en la proxima iteracion."""
        self._stop_event.set()
        logger.debug("contract_watchdog_job_stop_signalled")

    async def _correr_si_toca(self) -> dict[str, Any]:
        """Corre el chequeo solo si el latido ya cumplio el minimo entre corridas."""
        edad = self._edad_segundos()
        minimo = self._min_hours * 3600
        if edad is not None and edad < minimo:
            return {"corrido": False, "edad_segundos": edad}
        latido = await run_contract_watchdog_cycle(
            self._service,
            heartbeat_path=self._heartbeat_path,
            notifier=self._notifier,
            swallowed_counts=self._swallowed_counts,
            now=self._now,
        )
        return {"corrido": True, **latido}

    def _edad_segundos(self) -> int | None:
        latido = read_heartbeat(self._heartbeat_path)
        if not latido:
            return None
        return seconds_since(latido.get("last_run_at"), now=self._now())

    def _segundos_hasta_la_proxima(self) -> int:
        edad = self._edad_segundos()
        if edad is None:
            return MIN_WAIT_SECONDS
        return max(MIN_WAIT_SECONDS, self._min_hours * 3600 - edad)


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "MIN_HOURS_BETWEEN_RUNS",
    "ContractWatchdogJob",
    "run_contract_watchdog_cycle",
]
