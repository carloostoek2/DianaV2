"""REAL partial context derived from message history (no F2 tables).

Anexo H.3 Context always returns a non-null object with English keys only:
- ``waiting_for_reply_since`` (← esperando_respuesta_desde)
- ``is_first_message_of_day`` (← es_primer_mensaje_del_dia)

Never returns None from fetch. Uses history port only (no cross-retriever import).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import MessageHistoryPort

# Same role vocabulary as HistoryRetriever (local copy; no peer import).
_MAPPABLE_ROLES = frozenset({"vip", "owner"})


def _timestamp_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _parse_date(value: Any) -> date | None:
    """Best-effort date from port timestamp; unparseable → None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
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
        return {
            "waiting_for_reply_since": self._waiting_for_reply_since(messages),
            "is_first_message_of_day": self._is_first_message_of_day(messages),
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

    def _is_first_message_of_day(self, messages: list[dict]) -> bool:
        """True iff count of vip messages with parseable timestamp on today <= 1."""
        today = self._clock().date()
        vip_today = 0
        for row in messages:
            if not isinstance(row, dict):
                continue
            if str(row.get("role") or "") != "vip":
                continue
            msg_date = _parse_date(row.get("timestamp"))
            if msg_date is not None and msg_date == today:
                vip_today += 1
        return vip_today <= 1
