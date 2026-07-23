"""REAL retriever: recent messages for the current chat only.

Anexo H.3 History: bare list of ``{autor, texto, timestamp}`` (never None).
Empty chat → ``[]``. Bot/assistant/unknown roles are dropped.
Port rows keep ``role``/``text``; mapping is retriever-local only.
"""

from __future__ import annotations

from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import MessageHistoryPort

# Local copy of Director vocabulary (vip|dueña). Do not import Director.
_ROLE_TO_AUTOR: dict[str, str] = {
    "vip": "vip",
    "owner": "dueña",
}


def _timestamp_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class HistoryRetriever:
    """Fetch chat-scoped history via MessageHistoryPort (anti-contamination)."""

    def __init__(self, history_port: MessageHistoryPort, *, limit: int = 20) -> None:
        self._port = history_port
        self._limit = limit

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> list[dict]:
        _ = comprehension
        raw = await self._port.get_recent(turn.chat_id, limit=self._limit)
        out: list[dict] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            autor = _ROLE_TO_AUTOR.get(str(row.get("role") or ""))
            if autor is None:
                continue
            texto = row.get("text")
            if texto is None:
                texto = ""
            out.append(
                {
                    "autor": autor,
                    "texto": str(texto),
                    "timestamp": _timestamp_str(row.get("timestamp")),
                }
            )
        return out
