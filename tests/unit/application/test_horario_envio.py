"""Segunda linea del horario: el envio automatico no sale fuera de ventana (§4.27)."""

from __future__ import annotations

import pytest

from diana.application.turn_orchestrator import TurnOrchestrator


class _Horario:
    def __init__(self, abierto: bool) -> None:
        self.abierto = abierto

    async def esta_abierto(self, ahora):
        return self.abierto


class _HorarioRoto:
    async def esta_abierto(self, ahora):
        raise RuntimeError("ajuste roto")


class _SandboxActivo:
    def is_active(self, chat_id: int) -> bool:
        return True


def _orch(horario=None, sandbox=None) -> TurnOrchestrator:
    return TurnOrchestrator(
        coordinator=object(),
        director=object(),
        admin=object(),
        learning=object(),
        history=object(),
        horario=horario,
        sandbox=sandbox,
    )


@pytest.mark.asyncio
async def test_sin_horario_cableado_nunca_bloquea():
    assert await _orch()._fuera_de_horario(42) is False


@pytest.mark.asyncio
async def test_dentro_de_la_ventana_deja_enviar():
    assert await _orch(_Horario(True))._fuera_de_horario(42) is False


@pytest.mark.asyncio
async def test_fuera_de_la_ventana_degrada_el_envio():
    assert await _orch(_Horario(False))._fuera_de_horario(42) is True


@pytest.mark.asyncio
async def test_si_el_ajuste_falla_se_deja_enviar():
    assert await _orch(_HorarioRoto())._fuera_de_horario(42) is False


@pytest.mark.asyncio
async def test_el_sandbox_no_respeta_la_ventana():
    """Superficie de prueba de la duena: no se le aplica el horario."""
    assert await _orch(_Horario(False), _SandboxActivo())._fuera_de_horario(42) is False
