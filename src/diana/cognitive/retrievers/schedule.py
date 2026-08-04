"""REAL knowledge.schedule — fixed weekly agenda (Anexo H.3 / H9).

Time-of-day matching in a configured timezone (default America/Mexico_City).
Half-open windows: ``inicio <= hora < fin``. No embeddings. No application imports.
"""

from __future__ import annotations

import random
from typing import Any
from zoneinfo import ZoneInfo

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import ClockPort, PersonaCatalogProvider

_WEEKDAY_ES = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
)

# Fallbacks mirrored from cognitive/registry.py schedule parsing — only used
# for defensive rebuilds when a live catalog slice lacks a key (validation
# normally guarantees both are present).
_DEFAULT_SCHEDULE_TZ = "America/Mexico_City"
_DEFAULT_SCHEDULE_RESPONSES = ["Pues aquí entre cosas jsjsjs y tú?"]


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
        *,
        persona_catalog_provider: PersonaCatalogProvider | None = None,
    ) -> None:
        self._provider = persona_catalog_provider
        self._last_schedule: object = None
        self._clock = clock
        self._rng = rng
        self._set_schedule(bloques, default_responses, tz)

    def _set_schedule(
        self,
        bloques: list[dict],
        default_responses: list[str],
        tz: str,
    ) -> None:
        """(Re)build internal state from a schedule slice."""
        self._bloques = list(bloques)
        self._defaults = list(default_responses)
        try:
            self._tz = ZoneInfo(tz)
        except Exception:
            # Defensive: a bad timezone string must not crash the turn.
            self._tz = ZoneInfo(_DEFAULT_SCHEDULE_TZ)

    async def _maybe_refresh(self) -> None:
        """Pull a fresh schedule slice from the live catalog when it changed.

        A ``None`` slice (key missing) or a non-dict value keeps the last good
        state — never wipe on corrupt rows.
        """
        if self._provider is None:
            return
        catalog = await self._provider.get_catalog()
        if catalog is None:
            return
        schedule = catalog.get("schedule")
        if schedule is None:
            return
        if not isinstance(schedule, dict):
            return
        if schedule is not self._last_schedule:
            self._last_schedule = schedule
            self._set_schedule(
                schedule.get("bloques") or [],
                schedule.get("default_responses") or _DEFAULT_SCHEDULE_RESPONSES,
                schedule.get("timezone") or _DEFAULT_SCHEDULE_TZ,
            )

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> dict[str, Any]:
        _ = turn, comprehension
        await self._maybe_refresh()
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
