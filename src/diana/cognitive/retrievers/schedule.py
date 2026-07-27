"""REAL knowledge.schedule — fixed weekly agenda (Anexo H.3 / H9).

Time-of-day matching in a configured timezone (default America/Mexico_City).
Half-open windows: ``inicio <= hora < fin``. No embeddings. No application imports.
"""

from __future__ import annotations

import random
from typing import Any
from zoneinfo import ZoneInfo

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import ClockPort

_WEEKDAY_ES = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
)


class ScheduleRetriever:
    """Anexo H.3 knowledge.schedule — agenda semanal fija, sin embeddings."""

    fuente: str = "agenda_semanal_fija"

    def __init__(
        self,
        bloques: list[dict],
        default_responses: list[str],
        tz: str,
        clock: ClockPort,
        rng: Any = random,
    ) -> None:
        self._bloques = list(bloques)
        self._defaults = list(default_responses)
        self._tz = ZoneInfo(tz)
        self._clock = clock
        self._rng = rng

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> dict[str, Any]:
        _ = turn, comprehension
        now_local = self._clock.now().astimezone(self._tz)
        dia = _WEEKDAY_ES[now_local.weekday()]
        hora = now_local.strftime("%H:%M")
        for bloque in self._bloques:
            dias = bloque.get("dias") or []
            inicio = str(bloque.get("inicio") or "")
            fin = str(bloque.get("fin") or "")
            if dia in dias and inicio <= hora < fin:
                return {
                    "dia": dia,
                    "hora_actual": hora,
                    "tipo": "actividad",
                    "actividad": bloque["actividad"],
                }
        return {
            "dia": dia,
            "hora_actual": hora,
            "tipo": "respuesta_libre",
            "respuesta_sugerida": self._rng.choice(self._defaults),
        }
