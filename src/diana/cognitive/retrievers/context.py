"""REAL partial context derived from message history (no F2 tables).

Anexo H.3 Context always returns a non-null object with English keys only:
- ``waiting_for_reply_since`` (← esperando_respuesta_desde)
- ``is_first_message_of_day`` (← es_primer_mensaje_del_dia)
- ``dia_semana`` / ``hora_actual`` (H9.5, America/Mexico_City)

All three temporal fields use the America/Mexico_City civil day/clock:
``is_first_message_of_day`` compares VIP message dates after conversion to
CDMX (naive timestamps treated as UTC, same as history storage).

Never returns None from fetch. Uses history port only (no cross-retriever import).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import MessageHistoryPort

# Same role vocabulary as HistoryRetriever (local copy; no peer import).
_MAPPABLE_ROLES = frozenset({"vip", "owner"})

_CONTEXT_TZ = ZoneInfo("America/Mexico_City")
_WEEKDAY_ES = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
)


def _timestamp_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_cdmx(value: datetime) -> datetime:
    """Convert datetime to America/Mexico_City; naive values treated as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_CONTEXT_TZ)


def _parse_cdmx_date(value: Any) -> date | None:
    """Best-effort CDMX civil date from port timestamp; unparseable → None.

    Naive datetimes/ISO strings are treated as UTC, then converted to CDMX.
    Bare ``date`` values are interpreted as UTC midnight before conversion.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_cdmx(value).date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return _to_cdmx(datetime.combine(value, time.min, tzinfo=UTC)).date()
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _to_cdmx(parsed).date()
    return None


class ContextRetriever:
    """Derive H.3 conversation-state dict from history port only."""

    def __init__(
        self,
        history_port: MessageHistoryPort,
        *,
        limit: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._port = history_port
        self._limit = limit
        self._clock = clock or (lambda: datetime.now(UTC))

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> dict[str, Any]:
        _ = comprehension
        messages = await self._port.get_recent(turn.chat_id, limit=self._limit)
        now = self._clock()
        local = _to_cdmx(now)
        return {
            "waiting_for_reply_since": self._waiting_for_reply_since(messages),
            "is_first_message_of_day": self._is_first_message_of_day(
                messages, today=local.date()
            ),
            "dia_semana": _WEEKDAY_ES[local.weekday()],
            "hora_actual": local.strftime("%H:%M"),
        }

    def _waiting_for_reply_since(self, messages: list[dict]) -> str | None:
        """Walk end→start; last mappable vip → its ts; owner → None; none → None."""
        for row in reversed(messages):
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "")
            if role not in _MAPPABLE_ROLES:
                continue
            if role == "vip":
                return _timestamp_str(row.get("timestamp"))
            # owner / dueña last → not waiting
            return None
        return None

    def _is_first_message_of_day(
        self,
        messages: list[dict],
        *,
        today: date | None = None,
    ) -> bool:
        """True iff count of vip messages on today's CDMX civil day <= 1."""
        if today is None:
            today = _to_cdmx(self._clock()).date()
        vip_today = 0
        for row in messages:
            if not isinstance(row, dict):
                continue
            if str(row.get("role") or "") != "vip":
                continue
            msg_date = _parse_cdmx_date(row.get("timestamp"))
            if msg_date is not None and msg_date == today:
                vip_today += 1
        return vip_today <= 1
