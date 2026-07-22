"""REAL retriever: recent messages for the current chat only."""

from __future__ import annotations

from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import MessageHistoryPort


class HistoryRetriever:
    """Fetch chat-scoped history via MessageHistoryPort (anti-contamination)."""

    def __init__(self, history_port: MessageHistoryPort, *, limit: int = 20) -> None:
        self._port = history_port
        self._limit = limit

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> list[dict] | None:
        _ = comprehension
        return await self._port.get_recent(turn.chat_id, limit=self._limit)
