"""Horario de atencion (AGENTS §4.27): ventana, tolerancia y fail-open."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from diana.application.horario_atencion import (
    HorarioAtencion,
    HorarioAtencionService,
    parsear_hora,
    validar_horario,
)

CDMX = "America/Mexico_City"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _local(dia: int, hora: int, minuto: int = 0) -> datetime:
    """Instante UTC correspondiente a una hora civil de CDMX."""
    return datetime(2026, 11, dia, hora, minuto, tzinfo=ZoneInfo(CDMX)).astimezone(UTC)


# --------------------------------------------------------------------------
# Parseo y validacion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("09:00", time(9, 0)),
        ("23:59", time(23, 59)),
        ("00:00", time(0, 0)),
        ("9:00", None),
        ("24:00", None),
        ("09:60", None),
        ("nueve", None),
        (None, None),
    ],
)
def test_parsear_hora(texto, esperado):
    assert parsear_hora(texto) == esperado


def test_validar_horario_acepta_una_ventana_valida():
    assert validar_horario({"apertura": "09:00", "cierre": "23:00"}) is None


def test_validar_horario_rechaza_formato_incorrecto():
    error = validar_horario({"apertura": "nueve", "cierre": "23:00"})
    assert error is not None
    assert "HH:MM" in error


def test_validar_horario_rechaza_zona_inexistente():
    error = validar_horario({"zona_horaria": "Marte/Olimpo"})
    assert error is not None
    assert "zona horaria" in error.lower()


def test_validar_horario_acepta_cruce_de_medianoche():
    """La agenda de la persona lo prohibe; el horario de atencion NO."""
    assert validar_horario({"apertura": "21:00", "cierre": "03:00"}) is None


# --------------------------------------------------------------------------
# Construccion tolerante
# --------------------------------------------------------------------------


def test_desde_config_sin_blob_queda_desactivado():
    horario = HorarioAtencion.desde_config(None)
    assert horario.activo is False
    assert horario.esta_abierto(_utc(2026, 11, 7, 4, 0)) is True


def test_desde_config_con_basura_no_rompe_y_cae_a_defaults():
    horario = HorarioAtencion.desde_config(
        {"activo": True, "apertura": "zzz", "cierre": 42, "zona_horaria": 7}
    )
    assert horario.activo is True
    assert horario.apertura == time(9, 0)
    assert horario.cierre == time(23, 0)
    assert horario.zona_horaria == CDMX


def test_a_config_es_serializable_para_system_config():
    horario = HorarioAtencion(
        activo=True,
        zona_horaria=CDMX,
        apertura=time(21, 0),
        cierre=time(3, 0),
        pausa_manual_hasta=_utc(2026, 11, 7, 12, 0),
    )
    crudo = horario.a_config()
    assert crudo["apertura"] == "21:00"
    assert crudo["cierre"] == "03:00"
    assert HorarioAtencion.desde_config(crudo) == horario


# --------------------------------------------------------------------------
# Evaluacion de la ventana
# --------------------------------------------------------------------------


def test_horario_desactivado_esta_abierto_siempre():
    horario = HorarioAtencion(activo=False)
    assert horario.esta_abierto(_utc(2026, 11, 7, 4, 0)) is True


@pytest.mark.parametrize(
    "hora_local, abierto",
    [
        (8, False),  # antes de abrir
        (9, True),  # abre (semiabierto por la izquierda)
        (14, True),
        (22, True),
        (23, False),  # cierra (semiabierto por la derecha)
    ],
)
def test_ventana_normal_en_zona_local(hora_local, abierto):
    horario = HorarioAtencion(
        activo=True, zona_horaria=CDMX, apertura=time(9, 0), cierre=time(23, 0)
    )
    assert horario.esta_abierto(_local(7, hora_local)) is abierto


@pytest.mark.parametrize(
    "hora_local, abierto",
    [
        (12, False),  # fuera de la ventana
        (16, False),  # fuera de la ventana
        (21, True),  # abre
        (23, True),  # sigue abierto
        (2, True),  # madrugada del dia siguiente
        (4, False),  # ya cerro
    ],
)
def test_cruce_de_medianoche(hora_local, abierto):
    horario = HorarioAtencion(
        activo=True, zona_horaria=CDMX, apertura=time(21, 0), cierre=time(3, 0)
    )
    dia = 8 if hora_local < 12 else 7
    assert horario.esta_abierto(_local(dia, hora_local)) is abierto


def test_pausa_manual_manda_sobre_la_ventana():
    horario = HorarioAtencion(
        activo=True,
        zona_horaria=CDMX,
        apertura=time(9, 0),
        cierre=time(23, 0),
        pausa_manual_hasta=_utc(2026, 11, 7, 12, 0),
    )
    assert horario.esta_abierto(_utc(2026, 11, 7, 10, 0)) is True  # dentro de la pausa
    assert horario.esta_abierto(_utc(2026, 11, 7, 13, 0)) is False  # pausa vencida


def test_proxima_apertura_cuando_esta_cerrado():
    horario = HorarioAtencion(
        activo=True, zona_horaria=CDMX, apertura=time(9, 0), cierre=time(23, 0)
    )
    # 10:00 UTC = 04:00 local → la proxima apertura es hoy 09:00 local = 15:00 UTC
    assert horario.proxima_apertura(_utc(2026, 11, 7, 10, 0)) == _utc(2026, 11, 7, 15, 0)


def test_proxima_apertura_es_none_si_ya_esta_abierto():
    horario = HorarioAtencion(
        activo=True, zona_horaria=CDMX, apertura=time(9, 0), cierre=time(23, 0)
    )
    assert horario.proxima_apertura(_utc(2026, 11, 7, 20, 0)) is None


# --------------------------------------------------------------------------
# Servicio: cache, guardado y fail-open
# --------------------------------------------------------------------------


class _StoreFalso:
    def __init__(self, valor=None, *, falla: bool = False) -> None:
        self.valor = valor or {}
        self.falla = falla
        self.lecturas = 0
        self.escrituras: list[dict] = []

    async def get_horario_atencion(self):
        self.lecturas += 1
        if self.falla:
            raise RuntimeError("db caida")
        return dict(self.valor)

    async def set_horario_atencion(self, value):
        self.escrituras.append(dict(value))
        self.valor = dict(value)


@pytest.mark.asyncio
async def test_servicio_fail_open_si_la_base_no_responde():
    servicio = HorarioAtencionService(_StoreFalso(falla=True))
    assert await servicio.esta_abierto(_utc(2026, 11, 7, 10, 0)) is True


@pytest.mark.asyncio
async def test_servicio_con_bandera_apagada_no_lee_la_base():
    store = _StoreFalso({"activo": True, "apertura": "09:00", "cierre": "23:00"})
    servicio = HorarioAtencionService(store, enabled=False)
    assert await servicio.esta_abierto(_utc(2026, 11, 7, 10, 0)) is True
    assert store.lecturas == 0


@pytest.mark.asyncio
async def test_servicio_cachea_y_se_invalida_al_guardar():
    store = _StoreFalso({"activo": False})
    servicio = HorarioAtencionService(store, ttl_s=300.0)
    await servicio.estado()
    await servicio.estado()
    assert store.lecturas == 1

    await servicio.guardar({"activo": True, "apertura": "09:00", "cierre": "23:00"})
    assert store.escrituras[-1]["activo"] is True
    await servicio.estado()
    assert store.lecturas >= 3  # 2 del ciclo anterior + la relectura tras invalidar


@pytest.mark.asyncio
async def test_guardar_conserva_lo_que_no_se_envia():
    store = _StoreFalso({"activo": True, "apertura": "09:00", "cierre": "23:00"})
    servicio = HorarioAtencionService(store)
    await servicio.guardar({"cierre": "02:00"})
    assert store.escrituras[-1]["apertura"] == "09:00"
    assert store.escrituras[-1]["cierre"] == "02:00"
    assert store.escrituras[-1]["activo"] is True


@pytest.mark.asyncio
async def test_guardar_rechaza_hora_invalida():
    servicio = HorarioAtencionService(_StoreFalso())
    with pytest.raises(ValueError):
        await servicio.guardar({"apertura": "25:00"})
