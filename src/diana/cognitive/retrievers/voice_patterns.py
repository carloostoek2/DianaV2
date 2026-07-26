"""VoicePatternsRetriever — static catalog match by tags ∩ signals.

Returns at most one pattern ``{patron, uso}`` (first hit by list order)
or ``None``. No embeddings; pure in-memory set intersection.
"""

from __future__ import annotations

from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn


class VoicePatternsRetriever:
    """Fetch at most one voice pattern matching emotion/intent/topics."""

    def __init__(self, patterns: list[dict] | None = None) -> None:
        self._patterns: list[dict] = list(patterns or [])

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> dict[str, str] | None:
        _ = turn  # match is comprehension-driven only
        signals = {
            comprehension.emotion,
            comprehension.intent,
            *comprehension.topics,
        }
        for pattern in self._patterns:
            tags = pattern.get("tags") or []
            if not isinstance(tags, list):
                tags = [tags]
            tag_set = {str(t) for t in tags}
            if signals & tag_set:
                return {
                    "patron": str(pattern["patron"]),
                    "uso": str(pattern["uso"]),
                }
        return None


__all__ = ["VoicePatternsRetriever"]
