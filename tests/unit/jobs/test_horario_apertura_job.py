"""HorarioAperturaJob — la pasada no puede cancelar el turno retomado.

Bug real (2026-11-09): el presupuesto de una pasada era igual al intervalo
(300 s), y el turno retomado corre DENTRO de la pasada con su espera humana
previa (RandomDelayPolicy autónomo: 180–480 s). Cuando la espera sorteada
superaba los 300 s, ``asyncio.wait_for`` cancelaba el turno a mitad de camino:
quedaba en ``waiting_delay``, el chat pasaba a "chat_ocupado" y la conversación
no se retomaba hasta el siguiente reinicio.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from diana.application.horario_apertura_service import ResultadoBarrido
from diana.jobs.horario_apertura import HorarioAperturaJob

# Máximo de la espera humana autónoma (RandomDelayPolicy: 180–480 s).
_MAX_ESPERA_AUTONOMA_S = 480


class _StubService:
    """Servicio mínimo: un barrido que no retoma a nadie."""

    def __init__(self) -> None:
        self.pasadas = 0

    async def barrer(self) -> ResultadoBarrido:
        self.pasadas += 1
        return ResultadoBarrido(revisados=1, abiertos=0, saltados=1)


@pytest.mark.asyncio
async def test_pasada_espera_mas_que_la_espera_autonoma_maxima():
    """El presupuesto de una pasada cubre la espera más larga + el pipeline."""
    service = _StubService()
    job = HorarioAperturaJob(service, interval_seconds=300)
    timeouts: list[float] = []
    real_wait_for = asyncio.wait_for

    async def _record(coro, timeout):  # type: ignore[no-untyped-def]
        timeouts.append(timeout)
        return await real_wait_for(coro, timeout)

    with patch("diana.jobs.horario_apertura.asyncio.wait_for", _record):
        tarea = asyncio.create_task(job.start())
        for _ in range(50):
            if service.pasadas:
                break
            await asyncio.sleep(0.01)
        job._stop_event.set()  # type: ignore[attr-defined]
        await real_wait_for(tarea, timeout=5)

    assert service.pasadas == 1
    assert timeouts, "la pasada no llegó a ejecutarse"
    assert timeouts[0] >= 300 + _MAX_ESPERA_AUTONOMA_S
