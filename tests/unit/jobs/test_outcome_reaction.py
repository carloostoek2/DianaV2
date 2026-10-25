"""Job de respaldo de la reaccion: lee la respuesta del VIP del historial real.

La regresion que estas pruebas fijan: el historial entrega la marca de tiempo como
**texto ISO** (`rows_to_recent_messages`), no como `datetime`. El job exigia un
`datetime`, descartaba todas las filas y cerraba la ventana como ``silence`` aunque
el VIP hubiera contestado. Por eso la primera prueba arma sus filas pasando por el
serializador de verdad, no por un diccionario escrito a mano.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from diana.infrastructure.db.repositories.history import rows_to_recent_messages
from diana.jobs.outcome_reaction import first_vip_followup_text

ANCLA = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
VENTANA = 3600


@dataclass
class _Fila:
    """Lo minimo que `rows_to_recent_messages` lee de una fila del modelo."""

    role: str
    text: str
    timestamp: datetime
    telegram_message_id: int | None = None


def _historial(filas: list[_Fila]) -> list[dict]:
    """Historial tal como lo entrega el repositorio (mas nuevo primero)."""
    desc = sorted(filas, key=lambda fila: fila.timestamp, reverse=True)
    return rows_to_recent_messages(desc, limit=len(desc))


def test_lee_la_marca_de_tiempo_como_texto_iso() -> None:
    """Regresion: el historial entrega texto ISO y el job tiene que entenderlo."""
    rows = _historial(
        [
            _Fila("owner", "claro, te paso el precio", ANCLA - timedelta(minutes=1)),
            _Fila("vip", "gracias!", ANCLA + timedelta(minutes=5)),
        ]
    )

    assert isinstance(rows[0]["timestamp"], str), "el historial cambio de formato: revisar"

    assert first_vip_followup_text(rows, after=ANCLA, window_seconds=VENTANA) == "gracias!"


def test_elige_la_respuesta_mas_temprana_dentro_de_la_ventana() -> None:
    rows = _historial(
        [
            _Fila("vip", "la segunda", ANCLA + timedelta(minutes=20)),
            _Fila("vip", "la primera", ANCLA + timedelta(minutes=3)),
        ]
    )

    assert first_vip_followup_text(rows, after=ANCLA, window_seconds=VENTANA) == "la primera"


def test_ignora_lo_que_quedo_fuera_de_la_ventana() -> None:
    rows = _historial(
        [
            _Fila("vip", "antes de la entrega", ANCLA - timedelta(seconds=1)),
            _Fila("vip", "despues de la ventana", ANCLA + timedelta(seconds=VENTANA + 1)),
        ]
    )

    assert first_vip_followup_text(rows, after=ANCLA, window_seconds=VENTANA) is None


def test_sin_respuesta_del_vip_devuelve_none() -> None:
    rows = _historial(
        [
            _Fila("owner", "te paso el precio", ANCLA + timedelta(minutes=2)),
            _Fila("vip", "   ", ANCLA + timedelta(minutes=5)),
        ]
    )

    assert first_vip_followup_text(rows, after=ANCLA, window_seconds=VENTANA) is None


def test_acepta_datetime_ademas_de_texto() -> None:
    """Si el historial vuelve a entregar `datetime`, el job no puede romperse."""
    rows = [
        {"role": "vip", "text": "ya te digo", "timestamp": ANCLA + timedelta(minutes=4)},
        {"role": "vip", "text": "texto iso", "timestamp": (ANCLA + timedelta(minutes=9)).isoformat()},
    ]

    assert first_vip_followup_text(rows, after=ANCLA, window_seconds=VENTANA) == "ya te digo"


def test_una_marca_sin_zona_horaria_se_lee_en_utc() -> None:
    rows = [
        {
            "role": "vip",
            "text": "sin zona",
            "timestamp": (ANCLA + timedelta(minutes=7)).replace(tzinfo=None).isoformat(),
        }
    ]

    assert first_vip_followup_text(rows, after=ANCLA, window_seconds=VENTANA) == "sin zona"


def test_una_marca_ilegible_no_rompe_la_ventana() -> None:
    rows = [
        {"role": "vip", "text": "basura", "timestamp": "no es una fecha"},
        {"role": "vip", "text": "None", "timestamp": None},
        {"role": "vip", "text": "buena", "timestamp": (ANCLA + timedelta(minutes=6)).isoformat()},
    ]

    assert first_vip_followup_text(rows, after=ANCLA, window_seconds=VENTANA) == "buena"


def test_una_ancla_sin_zona_horaria_no_revienta() -> None:
    rows = [{"role": "vip", "text": "respuesta", "timestamp": ANCLA + timedelta(minutes=2)}]

    assert (
        first_vip_followup_text(
            rows, after=ANCLA.replace(tzinfo=None), window_seconds=VENTANA
        )
        == "respuesta"
    )
