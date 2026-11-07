"""Barrido de apertura del horario de atencion (AGENTS §4.27).

Al abrir la ventana se retoma lo que quedo pendiente: un turno normal con la
rafaga del VIP. Nunca se cuela un chat congelado, pausado, ocupado o una rafaga
con palabra prohibida.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.horario_apertura_service import (
    HorarioAperturaService,
    rafaga_pendiente,
    trae_media_sin_ver,
)
from diana.application.ports import BusinessConnectionRecord, VipRecord

AHORA = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)  # 09:00 en CDMX
CHAT = 8617981684


def _vip(**extra) -> VipRecord:
    base = {
        "id": uuid4(),
        "telegram_user_id": CHAT,
        "display_name": "Adan Olmos",
    }
    base.update(extra)
    return VipRecord(**base)


def _fila(rol: str, texto: str, *, minutos: int = 0, mid: int = 1) -> dict:
    return {
        "role": rol,
        "text": texto,
        "telegram_message_id": mid,
        "timestamp": (AHORA - timedelta(minutes=minutos)).isoformat(),
    }


class _Horario:
    def __init__(self, abierto: bool) -> None:
        self.abierto = abierto

    async def esta_abierto(self, ahora):
        return self.abierto


class _Runner:
    def __init__(self) -> None:
        self.llamadas = []

    async def handle_vip_message(self, incoming):
        self.llamadas.append(incoming)
        return uuid4()


class _History:
    def __init__(self, filas) -> None:
        self.filas = filas

    async def get_recent(self, chat_id, *, limit=20):
        return list(self.filas)


class _Vips:
    def __init__(self, vips) -> None:
        self.vips = vips

    async def list_active(self):
        return list(self.vips)


class _Conexiones:
    async def get_active(self):
        return BusinessConnectionRecord(
            business_connection_id="bc-1",
            user_id=1,
            user_chat_id=1,
            date=AHORA,
            can_reply=True,
            is_enabled=True,
        )


class _SinConexion:
    async def get_active(self):
        return None


class _Coordinator:
    def __init__(self, vivos=None) -> None:
        self.vivos = vivos or []

    async def list_non_terminal(self, chat_id):
        return list(self.vivos)


def _servicio(
    *, abierto=True, vips=None, filas=None, vivos=None, conexiones=None, matcher=None
):
    runner = _Runner()
    servicio = HorarioAperturaService(
        horario=_Horario(abierto),
        runner=runner,
        history=_History(filas or []),
        vips=_Vips(vips if vips is not None else [_vip()]),
        connections=conexiones or _Conexiones(),
        coordinator=_Coordinator(vivos),
        matcher_prohibidas=matcher,
        clock=lambda: AHORA,
    )
    return servicio, runner


# --------------------------------------------------------------------------
# Helpers puros
# --------------------------------------------------------------------------


def test_rafaga_pendiente_toma_solo_lo_del_vip_al_final():
    filas = [
        _fila("vip", "viejo", minutos=90, mid=1),
        _fila("owner", "ya te contesto", minutos=80, mid=2),
        _fila("vip", "hola?", minutos=70, mid=3),
        _fila("vip", "sigues ahi?", minutos=60, mid=4),
    ]
    pendientes = rafaga_pendiente(filas, ahora=AHORA)
    assert [r["text"] for r in pendientes] == ["hola?", "sigues ahi?"]


def test_rafaga_pendiente_descarta_lo_mas_viejo_que_24h():
    filas = [
        _fila("vip", "de la semana pasada", minutos=60 * 48, mid=1),
        _fila("vip", "de anoche", minutos=600, mid=2),
    ]
    pendientes = rafaga_pendiente(filas, ahora=AHORA)
    assert [r["text"] for r in pendientes] == ["de anoche"]


def test_rafaga_pendiente_vacia_si_la_ultima_fila_es_de_la_duena():
    filas = [
        _fila("vip", "hola", minutos=60, mid=1),
        _fila("owner", "hola, dime", minutos=50, mid=2),
    ]
    assert rafaga_pendiente(filas, ahora=AHORA) == []


@pytest.mark.parametrize(
    "textos, esperado",
    [
        (["[imagen]"], True),
        (["[imagen] mira esto"], True),
        (["[imagen parte de álbum]"], True),
        (["[video]"], True),
        (["[imagen: una foto de la playa]"], False),
        (["hola"], False),
    ],
)
def test_trae_media_sin_ver(textos, esperado):
    assert trae_media_sin_ver(textos) is esperado


# --------------------------------------------------------------------------
# Barrido
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_con_la_ventana_cerrada_no_hace_nada():
    servicio, runner = _servicio(
        abierto=False, filas=[_fila("vip", "hola", minutos=30)]
    )
    resultado = await servicio.barrer()
    assert resultado.cerrado is True
    assert runner.llamadas == []


@pytest.mark.asyncio
async def test_retoma_la_rafaga_pendiente_con_un_solo_turno():
    filas = [
        _fila("vip", "hola", minutos=90, mid=3),
        _fila("vip", "sigues ahi?", minutos=80, mid=4),
    ]
    servicio, runner = _servicio(filas=filas)
    resultado = await servicio.barrer()
    assert resultado.abiertos == 1
    assert len(runner.llamadas) == 1
    incoming = runner.llamadas[0]
    assert "sigues ahi?" in incoming.text
    # El id real permite que el historial se actualice en vez de duplicarse.
    assert incoming.telegram_message_id == 4
    assert incoming.skip_coalesce is False


@pytest.mark.asyncio
async def test_sin_mensajes_pendientes_no_arranca_nada():
    servicio, runner = _servicio(filas=[_fila("owner", "te escribo yo", minutos=10)])
    resultado = await servicio.barrer()
    assert resultado.abiertos == 0
    assert runner.llamadas == []


@pytest.mark.asyncio
async def test_chat_con_turno_vivo_se_salta():
    servicio, runner = _servicio(
        filas=[_fila("vip", "hola", minutos=30)], vivos=[object()]
    )
    resultado = await servicio.barrer()
    assert resultado.abiertos == 0
    assert runner.llamadas == []


@pytest.mark.asyncio
async def test_vip_congelado_o_pausado_se_salta():
    congelado = _vip(frozen_until=AHORA + timedelta(hours=2))
    servicio, runner = _servicio(
        vips=[congelado], filas=[_fila("vip", "hola", minutos=30)]
    )
    assert (await servicio.barrer()).abiertos == 0
    assert runner.llamadas == []

    pausado = _vip(paused_until=AHORA + timedelta(hours=2))
    servicio, runner = _servicio(
        vips=[pausado], filas=[_fila("vip", "hola", minutos=30)]
    )
    assert (await servicio.barrer()).abiertos == 0
    assert runner.llamadas == []


@pytest.mark.asyncio
async def test_pausa_vencida_no_bloquea():
    vencido = _vip(paused_until=AHORA - timedelta(hours=2))
    servicio, runner = _servicio(
        vips=[vencido], filas=[_fila("vip", "hola", minutos=30)]
    )
    assert (await servicio.barrer()).abiertos == 1
    assert len(runner.llamadas) == 1


@pytest.mark.asyncio
async def test_sin_conexion_de_negocios_no_arranca():
    servicio, runner = _servicio(
        filas=[_fila("vip", "hola", minutos=30)], conexiones=_SinConexion()
    )
    assert (await servicio.barrer()).abiertos == 0
    assert runner.llamadas == []


@pytest.mark.asyncio
async def test_media_sin_ver_queda_marcada_para_la_cola_de_la_duena():
    servicio, runner = _servicio(filas=[_fila("vip", "[imagen]", minutos=30)])
    await servicio.barrer()
    assert runner.llamadas[0].media_unverified is True


@pytest.mark.asyncio
async def test_palabra_prohibida_no_se_contesta_por_el_pipeline_normal():
    servicio, runner = _servicio(
        filas=[_fila("vip", "cuanto cuesta", minutos=30)],
        matcher=lambda texto: ["cuesta"] if "cuesta" in texto else [],
    )
    assert (await servicio.barrer()).abiertos == 0
    assert runner.llamadas == []
