"""HorarioAtencionMiddleware (AGENTS §4.27).

Fuera de la ventana: se guarda el mensaje y se corta la cadena. No hay turno,
no hay traza, no hay metrica y no se marca leido. Dentro: todo sigue igual.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

from diana.application.memory import InMemoryMessageHistoryWriter
from diana.telegram.middlewares.horario import HorarioAtencionMiddleware

VIP_ID = 8617981684
AHORA = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)


class _HorarioFijo:
    def __init__(self, abierto: bool, *, falla: bool = False) -> None:
        self.abierto = abierto
        self.falla = falla

    async def esta_abierto(self, ahora):
        if self.falla:
            raise RuntimeError("ajuste roto")
        return self.abierto


def _mensaje(
    *, texto: str | None = "hola", foto: bool = False, editado: bool = False
) -> Message:
    kwargs = {}
    if foto:
        kwargs["photo"] = [
            PhotoSize(file_id="p1", file_unique_id="u1", width=9, height=9)
        ]
    else:
        kwargs["text"] = texto
    if editado:
        kwargs["edit_date"] = 1
    return Message(
        message_id=77,
        date=0,
        chat=Chat(id=VIP_ID, type="private"),
        from_user=User(id=VIP_ID, is_bot=False, first_name="Adan"),
        business_connection_id="bc-1",
        **kwargs,
    )


def _data(**extra):
    base = {
        "vip_id": uuid4(),
        "business_connection_id": "bc-1",
    }
    base.update(extra)
    return base


async def _correr(horario, *, enabled=True, data=None, event=None):
    hist = InMemoryMessageHistoryWriter()
    mw = HorarioAtencionMiddleware(
        horario=horario, history=hist, enabled=enabled, clock=lambda: AHORA
    )
    handler = AsyncMock(return_value="paso")
    resultado = await mw(handler, event or _mensaje(), data or _data())  # type: ignore[arg-type]
    return resultado, handler, hist


@pytest.mark.asyncio
async def test_dentro_de_horario_sigue_el_camino_normal():
    resultado, handler, hist = await _correr(_HorarioFijo(True))
    assert resultado == "paso"
    handler.assert_awaited_once()
    assert await hist.get_recent(VIP_ID) == []


@pytest.mark.asyncio
async def test_fuera_de_horario_no_llama_al_handler():
    resultado, handler, _ = await _correr(_HorarioFijo(False))
    assert resultado is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_fuera_de_horario_guarda_el_mensaje_para_retomarlo():
    _, _, hist = await _correr(_HorarioFijo(False))
    filas = await hist.get_recent(VIP_ID)
    assert len(filas) == 1
    assert filas[0]["role"] == "vip"
    assert filas[0]["text"] == "hola"
    assert filas[0]["telegram_message_id"] == 77


@pytest.mark.asyncio
async def test_fuera_de_horario_guarda_la_etiqueta_de_media_sin_analizarla():
    _, _, hist = await _correr(_HorarioFijo(False), event=_mensaje(foto=True))
    filas = await hist.get_recent(VIP_ID)
    assert filas[0]["text"] == "[imagen]"


@pytest.mark.asyncio
async def test_edicion_fuera_de_horario_no_duplica_la_fila():
    _, _, hist = await _correr(_HorarioFijo(False))
    _, _, _ = await _correr(_HorarioFijo(False), event=_mensaje(editado=True))
    filas = await hist.get_recent(VIP_ID)
    assert len(filas) == 1


@pytest.mark.asyncio
async def test_bandera_apagada_es_inerte_aunque_la_ventana_este_cerrada():
    resultado, handler, hist = await _correr(_HorarioFijo(False), enabled=False)
    assert resultado == "paso"
    handler.assert_awaited_once()
    assert await hist.get_recent(VIP_ID) == []


@pytest.mark.asyncio
async def test_canal_de_atencion_no_se_toca():
    resultado, handler, _ = await _correr(
        _HorarioFijo(False), data=_data(channel_type="atencion")
    )
    assert resultado == "paso"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_sandbox_no_se_toca():
    resultado, handler, _ = await _correr(
        _HorarioFijo(False), data=_data(sandbox_active=True)
    )
    assert resultado == "paso"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_mensaje_privado_de_la_duena_no_se_toca():
    """El panel vive en el chat privado: sin conexion de negocios no aplica."""
    data = {"vip_id": uuid4()}
    resultado, handler, _ = await _correr(_HorarioFijo(False), data=data)
    assert resultado == "paso"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_si_el_ajuste_falla_se_responde_fail_open():
    resultado, handler, _ = await _correr(_HorarioFijo(False, falla=True))
    assert resultado == "paso"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_si_el_historial_falla_no_rompe_el_corte():
    class _HistorialRoto:
        async def append(self, *a, **k):
            raise RuntimeError("db caida")

    handler = AsyncMock(return_value="paso")
    mw = HorarioAtencionMiddleware(
        horario=_HorarioFijo(False), history=_HistorialRoto(), clock=lambda: AHORA
    )
    assert await mw(handler, _mensaje(), _data()) is None  # type: ignore[arg-type]
    handler.assert_not_awaited()
