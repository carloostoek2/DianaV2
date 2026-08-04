"""H9 schedule retriever — fixed weekly agenda matching (Strict TDD golds)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.retrievers.schedule import ScheduleRetriever

# Production-like mini catalog (H9.2 subset + full matching windows used in golds).
_BLOQUES = [
    {
        "dias": ["lunes", "martes", "miercoles", "jueves", "viernes"],
        "inicio": "09:00",
        "fin": "12:00",
        "actividad": "en el servicio social, en un instituto de adicciones",
    },
    {
        "dias": ["lunes", "martes", "miercoles", "jueves"],
        "inicio": "16:00",
        "fin": "21:00",
        "actividad": "en las prácticas profesionales, en una casa hogar",
    },
    {
        "dias": ["viernes"],
        "inicio": "17:00",
        "fin": "20:00",
        "actividad": "en el diplomado de gamificación",
    },
    {
        "dias": ["domingo"],
        "inicio": "00:00",
        "fin": "23:59",
        "actividad": "con su hermana, la mayor parte del día",
    },
]
_DEFAULTS = [
    "Pues aquí entre cosas jsjsjs y tú?",
    "Ya ni sé jsjsj estoy con mil cosas!",
    "En modo zombi tratando de recuperar el alma 😁",
]
_TZ = "America/Mexico_City"


class _FixedClock:
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


class _FixedRng:
    def __init__(self, choice_value: str) -> None:
        self._choice_value = choice_value
        self.choice_calls: list[list[str]] = []

    def choice(self, seq: list[str]) -> str:
        self.choice_calls.append(list(seq))
        return self._choice_value


def _turn() -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text="Y ahora qué haces?")


def _comprehension() -> Comprehension:
    return Comprehension(
        intent="ask_activity",
        topics=[],
        emotion="neutral",
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=False,
        needs_schedule=True,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
    )


def _retriever(
    when_utc: datetime,
    *,
    rng: object | None = None,
) -> ScheduleRetriever:
    return ScheduleRetriever(
        list(_BLOQUES),
        list(_DEFAULTS),
        _TZ,
        _FixedClock(when_utc),
        rng=rng if rng is not None else _FixedRng(_DEFAULTS[0]),
    )


@pytest.mark.asyncio
async def test_thursday_1600_cdmx_inicio_inclusive_practicas() -> None:
    """Half-open lock: inicio inclusive — jueves 16:00 CDMX → prácticas."""
    # 2026-07-23 Thursday; 22:00 UTC = 16:00 America/Mexico_City (no DST).
    r = _retriever(datetime(2026, 7, 23, 22, 0, tzinfo=UTC))
    result = await r.fetch(_turn(), _comprehension())
    assert result["tipo"] == "actividad"
    assert result["dia"] == "jueves"
    assert result["hora_actual"] == "16:00"
    assert "prácticas profesionales" in result["actividad"]


@pytest.mark.asyncio
async def test_thursday_1700_cdmx_practicas() -> None:
    """A1 gold: jueves 17:00 CDMX → prácticas (16:00–21:00)."""
    # 2026-07-23 is Thursday; 23:00 UTC = 17:00 America/Mexico_City (no DST).
    r = _retriever(datetime(2026, 7, 23, 23, 0, tzinfo=UTC))
    result = await r.fetch(_turn(), _comprehension())
    assert r.fuente == "agenda_semanal_fija"
    assert result is not None
    assert result["tipo"] == "actividad"
    assert result["dia"] == "jueves"
    assert result["hora_actual"] == "17:00"
    assert "prácticas profesionales" in result["actividad"]


@pytest.mark.asyncio
async def test_thursday_1300_cdmx_respuesta_libre() -> None:
    """A1 gold: jueves 13:00 CDMX is a gap → respuesta_libre."""
    fixed = "Pues aquí entre cosas jsjsjs y tú?"
    rng = _FixedRng(fixed)
    r = _retriever(datetime(2026, 7, 23, 19, 0, tzinfo=UTC), rng=rng)
    result = await r.fetch(_turn(), _comprehension())
    assert result["tipo"] == "respuesta_libre"
    assert result["dia"] == "jueves"
    assert result["hora_actual"] == "13:00"
    assert result["respuesta_sugerida"] == fixed
    assert rng.choice_calls and rng.choice_calls[0] == _DEFAULTS


@pytest.mark.asyncio
async def test_thursday_1430_cdmx_respuesta_libre_not_practicas() -> None:
    """PLAN correction: 14:30 is gap (prácticas start 16:00), not actividad."""
    r = _retriever(datetime(2026, 7, 23, 20, 30, tzinfo=UTC))
    result = await r.fetch(_turn(), _comprehension())
    assert result["tipo"] == "respuesta_libre"
    assert "actividad" not in result or result.get("tipo") != "actividad"


@pytest.mark.asyncio
async def test_sunday_1200_hermana() -> None:
    """A1 gold: domingo 12:00 CDMX → hermana."""
    r = _retriever(datetime(2026, 7, 26, 18, 0, tzinfo=UTC))
    result = await r.fetch(_turn(), _comprehension())
    assert result["tipo"] == "actividad"
    assert result["dia"] == "domingo"
    assert result["hora_actual"] == "12:00"
    assert "hermana" in result["actividad"]


@pytest.mark.asyncio
async def test_fin_exclusive_friday_1200_not_servicio() -> None:
    """Half-open: viernes 12:00 not in 09:00–12:00 servicio → gap until diplomado."""
    r = _retriever(datetime(2026, 7, 24, 18, 0, tzinfo=UTC))
    result = await r.fetch(_turn(), _comprehension())
    assert result["tipo"] == "respuesta_libre"
    assert result["dia"] == "viernes"
    assert result["hora_actual"] == "12:00"


@pytest.mark.asyncio
async def test_sunday_2359_fin_exclusive_respuesta_libre() -> None:
    """domingo fin=23:59 exclusive → 23:59 is respuesta_libre."""
    r = _retriever(datetime(2026, 7, 27, 5, 59, tzinfo=UTC))
    result = await r.fetch(_turn(), _comprehension())
    assert result["tipo"] == "respuesta_libre"
    assert result["dia"] == "domingo"
    assert result["hora_actual"] == "23:59"


@pytest.mark.asyncio
async def test_empty_bloques_always_respuesta_libre() -> None:
    r = ScheduleRetriever(
        [],
        list(_DEFAULTS),
        _TZ,
        _FixedClock(datetime(2026, 7, 23, 23, 0, tzinfo=UTC)),
        rng=_FixedRng(_DEFAULTS[1]),
    )
    result = await r.fetch(_turn(), _comprehension())
    assert result["tipo"] == "respuesta_libre"
    assert result["respuesta_sugerida"] == _DEFAULTS[1]


class _FakeProvider:
    def __init__(self, catalog) -> None:
        self.catalog = catalog

    async def get_catalog(self):
        return self.catalog


@pytest.mark.asyncio
async def test_schedule_hot_swap_via_provider() -> None:
    """ScheduleRetriever picks up a new schedule slice when the catalog changes."""
    monday_morning = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)  # lunes 09:00 CDMX (UTC-6)

    v1_schedule = {
        "timezone": "America/Mexico_City",
        "default_responses": ["v1"],
        "bloques": [
            {"dias": ["lunes"], "inicio": "09:00", "fin": "12:00", "actividad": "actividad v1"}
        ],
    }
    v2_schedule = {
        "timezone": "America/Mexico_City",
        "default_responses": ["v2"],
        "bloques": [
            {"dias": ["lunes"], "inicio": "09:00", "fin": "12:00", "actividad": "actividad v2"}
        ],
    }
    provider = _FakeProvider({"schedule": dict(v1_schedule)})
    retriever = ScheduleRetriever(
        bloques=[],
        default_responses=["seed"],
        tz="America/Mexico_City",
        clock=_FixedClock(monday_morning),
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )

    result = await retriever.fetch(_turn(), _comprehension())
    assert result["tipo"] == "actividad"
    assert result["actividad"] == "actividad v1"

    provider.catalog = {"schedule": dict(v2_schedule)}
    result = await retriever.fetch(_turn(), _comprehension())
    assert result["actividad"] == "actividad v2"


@pytest.mark.asyncio
async def test_schedule_provider_none_falls_back() -> None:
    """Provider returning None keeps the constructor schedule state."""
    monday_morning = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)  # lunes 09:00 CDMX
    provider = _FakeProvider(None)
    retriever = ScheduleRetriever(
        bloques=[
            {"dias": ["lunes"], "inicio": "09:00", "fin": "12:00", "actividad": "constructor state"}
        ],
        default_responses=["seed"],
        tz="America/Mexico_City",
        clock=_FixedClock(monday_morning),
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )
    result = await retriever.fetch(_turn(), _comprehension())
    assert result["tipo"] == "actividad"
    assert result["actividad"] == "constructor state"


@pytest.mark.asyncio
async def test_schedule_refresh_invalid_timezone_falls_back() -> None:
    """A bogus timezone in a live slice must not crash; falls back to default."""
    monday_morning = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    provider = _FakeProvider(
        {
            "schedule": {
                "timezone": "Bogus/Zone",
                "default_responses": ["resp"],
                "bloques": [
                    {"dias": ["lunes"], "inicio": "09:00", "fin": "12:00", "actividad": "act"}
                ],
            }
        }
    )
    retriever = ScheduleRetriever(
        bloques=[], default_responses=["seed"], tz="America/Mexico_City",
        clock=_FixedClock(monday_morning),
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )
    result = await retriever.fetch(_turn(), _comprehension())
    assert result is not None
    assert result["tipo"] == "actividad"
    assert result["actividad"] == "act"


@pytest.mark.asyncio
async def test_schedule_refresh_missing_keys_uses_defaults() -> None:
    """A live slice without timezone/default_responses falls back to defaults."""
    monday_morning = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    provider = _FakeProvider({"schedule": {"bloques": []}})
    retriever = ScheduleRetriever(
        bloques=[], default_responses=["seed"], tz="America/Mexico_City",
        clock=_FixedClock(monday_morning),
        persona_catalog_provider=provider,  # type: ignore[arg-type]
    )
    result = await retriever.fetch(_turn(), _comprehension())
    assert result["tipo"] == "respuesta_libre"
    # missing keys fall back to the retriever's mirrored default response
    assert result["respuesta_sugerida"] == "Pues aquí entre cosas jsjsjs y tú?"
