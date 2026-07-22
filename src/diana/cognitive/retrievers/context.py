"""REAL partial context derived from message history (no F2 tables)."""

from __future__ import annotations

from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import MessageHistoryPort

_PREVIEW_LEN = 120


class ContextRetriever:
    """Derive a small conversation-state dict from history port only."""

    def __init__(self, history_port: MessageHistoryPort, *, limit: int = 20) -> None:
        self._port = history_port
        self._limit = limit

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> dict[str, Any] | None:
        _ = comprehension
        messages = await self._port.get_recent(turn.chat_id, limit=self._limit)
        if not messages:
            return {
                "message_count": 0,
                "last_role": None,
                "last_text_preview": "",
            }
        last = messages[-1]
        text = str(last.get("text", "") or "")
        return {
            "message_count": len(messages),
            "last_role": last.get("role"),
            "last_text_preview": text[:_PREVIEW_LEN],
        }
