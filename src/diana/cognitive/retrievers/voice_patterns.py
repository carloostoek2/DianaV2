"""VoicePatternsRetriever — static catalog match by tags ∩ signals.

Returns at most one pattern ``{patron, uso}`` or ``None``. Prefers largest
|signals ∩ tags|; ties keep catalog list order. No embeddings.
"""

from __future__ import annotations

from diana.cognitive.models import Comprehension, IncomingTurn


def _norm(token: object) -> str:
    return str(token).strip().lower()


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
            _norm(comprehension.emotion),
            _norm(comprehension.intent),
            *(_norm(t) for t in comprehension.topics if str(t).strip()),
        }
        best: dict[str, str] | None = None
        best_score = 0
        for pattern in self._patterns:
            tags = pattern.get("tags") or []
            if not isinstance(tags, list):
                tags = [tags]
            tag_set = {_norm(t) for t in tags if str(t).strip()}
            score = len(signals & tag_set)
            if score > best_score:
                best_score = score
                best = {
                    "patron": str(pattern["patron"]),
                    "uso": str(pattern["uso"]),
                }
        return best


__all__ = ["VoicePatternsRetriever"]
