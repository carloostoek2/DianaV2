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
# normally guarantees both are present). Channel-neutral: the same fallback is
# reachable from an atencion turn (provider returning None), so it must not
# carry VIP-flavored slang (B3 style rules).
_DEFAULT_SCHEDULE_TZ = "America/Mexico_City"
_DEFAULT_SCHEDULE_RESPONSES = ["Estoy al pendiente de tus mensajes."]


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
        self._last_schedule: dict[str, object] = {}
        self._bloques: dict[str, list[dict]] = {}
        self._defaults: dict[str, list[str]] = {}
        self._tz: dict[str, ZoneInfo] = {}
        self._clock = clock
        self._rng = rng
        self._set_schedule("vip", bloques, default_responses, tz)

    def _set_schedule(
        self,
        channel_type: str,
        bloques: list[dict],
        default_responses: list[str],
        tz: str,
    ) -> None:
        """(Re)build per-channel state from a schedule slice."""
        self._bloques[channel_type] = list(bloques)
        self._defaults[channel_type] = list(default_responses)
        try:
            self._tz[channel_type] = ZoneInfo(tz)
        except Exception:
            # Defensive: a bad timezone string must not crash the turn.
            self._tz[channel_type] = ZoneInfo(_DEFAULT_SCHEDULE_TZ)

    async def _maybe_refresh(self, channel_type: str) -> None:
        """Pull a fresh per-channel schedule slice from the live catalog.

        The identity cache is keyed by channel so switching channels
        re-refreshes (an atencion turn must never reuse the VIP slice). A
        ``None`` slice (key missing) or a non-dict value keeps the last good
        state — never wipe on corrupt rows.
        """
        if self._provider is None:
            return
        catalog = await self._provider.get_catalog(channel_type=channel_type)
        if catalog is None:
            return
        schedule = catalog.get("schedule")
        if schedule is None:
            return
        if not isinstance(schedule, dict):
            return
        if self._last_schedule.get(channel_type) is not schedule:
            self._last_schedule[channel_type] = schedule
            self._set_schedule(
                channel_type,
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
        channel_type = turn.channel_type
        await self._maybe_refresh(channel_type)
        now_local = self._clock.now().astimezone(
            self._tz.get(channel_type, ZoneInfo(_DEFAULT_SCHEDULE_TZ))
        )
        dia = _WEEKDAY_ES[now_local.weekday()]
        hora = now_local.strftime("%H:%M")
        for bloque in self._bloques.get(channel_type) or []:
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
        defaults = self._defaults.get(channel_type) or _DEFAULT_SCHEDULE_RESPONSES
        return {
            "dia": dia,
            "hora_actual": hora,
            "tipo": "respuesta_libre",
            "respuesta_sugerida": self._rng.choice(defaults),
        }
