"""Panel 🕒 Horario de atención (AGENTS §4.27)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from unittest.mock import MagicMock

import pytest

import diana.telegram.handlers.menu as menu
from diana.application.horario_atencion import HorarioAtencion, validar_horario

AHORA = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)  # 09:00 en CDMX


class _Servicio:
    """Doble del HorarioAtencionService: guarda y devuelve el estado aplicado."""

    def __init__(self, estado: HorarioAtencion | None = None) -> None:
        self._estado = estado or HorarioAtencion()
        self.guardados: list[dict] = []

    async def estado(self) -> HorarioAtencion:
        return self._estado

    async def guardar(self, raw: dict) -> HorarioAtencion:
        # El servicio real valida antes de escribir; el doble hace lo mismo.
        error = validar_horario(raw)
        if error is not None:
            raise ValueError(error)
        self.guardados.append(dict(raw))
        self._estado = HorarioAtencion.desde_config(
            {**self._estado.a_config(), **raw}
        )
        return self._estado


@pytest.fixture
def mostrado(monkeypatch):
    capturado: dict = {}

    async def _show(message, text, keyboard=None):
        capturado["texto"] = text
        capturado["teclado"] = keyboard

    monkeypatch.setattr(menu, "_show", _show)
    return capturado


@pytest.fixture
def respondido(monkeypatch):
    capturado: dict = {}

    async def _edit_or_answer(bot, text, *, session=None, fallback=None, keyboard=None):
        capturado["texto"] = text
        capturado["teclado"] = keyboard

    monkeypatch.setattr(menu, "_edit_or_answer", _edit_or_answer)
    return capturado


def _sesiones() -> menu.MenuSessionStore:
    return menu.MenuSessionStore()


# --------------------------------------------------------------------------
# Texto de estado
# --------------------------------------------------------------------------


def test_texto_apagado_avisa_que_responde_24_horas():
    texto = menu._texto_horario(HorarioAtencion(), AHORA)
    assert "APAGADO" in texto
    assert "24" not in texto  # el detalle vive en el boton


def test_texto_abierto_y_cerrado():
    abierto = HorarioAtencion(
        activo=True, apertura=time(9, 0), cierre=time(23, 0)
    )
    assert "ABIERTO" in menu._texto_horario(abierto, AHORA)
    cerrado_en_hora = AHORA.replace(hour=10)  # 04:00 local
    assert "CERRADO" in menu._texto_horario(abierto, cerrado_en_hora)


# --------------------------------------------------------------------------
# Acciones del submenú
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_encender_y_apagar(mostrado):
    servicio = _Servicio(HorarioAtencion(activo=False))
    await menu._dispatch_horario(
        MagicMock(), action="hours_toggle", horario=servicio,
        sessions=_sesiones(), actor_id=1,
    )
    assert servicio.guardados[-1] == {"activo": True}

    await menu._dispatch_horario(
        MagicMock(), action="hours_toggle", horario=servicio,
        sessions=_sesiones(), actor_id=1,
    )
    assert servicio.guardados[-1] == {"activo": False}


@pytest.mark.asyncio
async def test_pausa_temporal_guarda_la_hora_de_fin(mostrado):
    servicio = _Servicio(HorarioAtencion(activo=True))
    await menu._dispatch_horario(
        MagicMock(), action="hours_pause_60", horario=servicio,
        sessions=_sesiones(), actor_id=1,
    )
    hasta = datetime.fromisoformat(servicio.guardados[-1]["pausa_manual_hasta"])
    assert timedelta(minutes=59) < hasta - datetime.now(UTC) <= timedelta(minutes=61)


@pytest.mark.asyncio
async def test_quitar_la_pausa(mostrado):
    servicio = _Servicio(
        HorarioAtencion(activo=True, pausa_manual_hasta=AHORA + timedelta(hours=1))
    )
    await menu._dispatch_horario(
        MagicMock(), action="hours_pause_off", horario=servicio,
        sessions=_sesiones(), actor_id=1,
    )
    assert servicio.guardados[-1] == {"pausa_manual_hasta": None}


@pytest.mark.asyncio
async def test_cambiar_horas_abre_la_captura_de_texto(mostrado):
    sesiones = _sesiones()
    await menu._dispatch_horario(
        MagicMock(), action="hours_set", horario=_Servicio(),
        sessions=sesiones, actor_id=1,
    )
    assert sesiones.has_active(1)
    assert "09:00-23:00" in mostrado["texto"]


@pytest.mark.asyncio
async def test_sin_servicio_la_seccion_avisa(mostrado):
    await menu._dispatch_horario(
        MagicMock(), action="hours", horario=None,
        sessions=_sesiones(), actor_id=1,
    )
    assert "no está disponible" in mostrado["texto"]


# --------------------------------------------------------------------------
# Captura de texto
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_texto_valido_guarda_y_enciende(respondido):
    servicio = _Servicio()
    mensaje = MagicMock()
    mensaje.text = " 21:00 - 03:00 "
    await menu._handle_horario_text(
        mensaje, MagicMock(), menu.MenuSession(kind="horario_ventana"),
        servicio, _sesiones(),
    )
    assert servicio.guardados[-1] == {
        "apertura": "21:00", "cierre": "03:00", "activo": True,
    }
    assert "ventana" in respondido["texto"].lower() or "ABIERTO" in respondido["texto"]


@pytest.mark.asyncio
async def test_texto_invalido_no_guarda(respondido):
    servicio = _Servicio()
    mensaje = MagicMock()
    mensaje.text = "nueve a once"
    await menu._handle_horario_text(
        mensaje, MagicMock(), menu.MenuSession(kind="horario_ventana"),
        servicio, _sesiones(),
    )
    assert servicio.guardados == []
    assert "No entendí" in respondido["texto"]


@pytest.mark.asyncio
async def test_hora_fuera_de_rango_no_guarda(respondido):
    servicio = _Servicio()
    mensaje = MagicMock()
    mensaje.text = "25:00-03:00"
    await menu._handle_horario_text(
        mensaje, MagicMock(), menu.MenuSession(kind="horario_ventana"),
        servicio, _sesiones(),
    )
    assert servicio.guardados == []
    assert "No pude guardar" in respondido["texto"]
