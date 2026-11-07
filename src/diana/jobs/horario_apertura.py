"""HorarioAperturaJob — retoma al abrir la ventana lo que quedó sin responder.

Job periódico de la capa de aplicación (AGENTS §4.27). No decide nada por su
cuenta: delega en ``HorarioAperturaService``, que a su vez mete los mensajes
pendientes por el pipeline normal. Con la ventana cerrada no hace nada.
"""

from __future__ import annotations

import asyncio
import logging
import time

from diana.application.horario_apertura_service import (
    HorarioAperturaService,
    ResultadoBarrido,
)

logger = logging.getLogger("diana.jobs")


async def run_una_pasada(service: HorarioAperturaService) -> ResultadoBarrido:
    """Una pasada del barrido. Nunca lanza."""
    try:
        return await service.barrer()
    except Exception:
        logger.exception("horario_apertura_run_error")
        return ResultadoBarrido(motivo="error")


class HorarioAperturaJob:
    """Corre el barrido cada ``interval_seconds``.

    ``start()`` es de una sola pasada: cuando retorna (después de ``stop()``)
    hay que crear una instancia nueva para reanudarlo.
    """

    def __init__(
        self,
        service: HorarioAperturaService,
        *,
        interval_seconds: int = 300,
    ) -> None:
        self._service = service
        self._interval = max(30, int(interval_seconds))
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        logger.info(
            "horario_apertura_job_started",
            extra={"interval_seconds": self._interval},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                resultado = await asyncio.wait_for(
                    run_una_pasada(self._service),
                    timeout=self._interval,
                )
                if resultado.abiertos:
                    logger.info(
                        "horario_apertura_job_tick",
                        extra={
                            "abiertos": resultado.abiertos,
                            "saltados": resultado.saltados,
                            "duration_ms": int((time.monotonic() - t0) * 1000),
                        },
                    )
            except TimeoutError:
                logger.warning("horario_apertura_run_timeout")
            except Exception:
                logger.exception("horario_apertura_run_error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._interval
                )
                break
            except TimeoutError:
                continue

        logger.info("horario_apertura_job_stopped")

    async def stop(self) -> None:
        self._stop_event.set()
        logger.debug("horario_apertura_job_stop_signalled")


__all__ = ["HorarioAperturaJob", "run_una_pasada"]
