"""VoicePatternsRetriever — static catalog match by tags ∩ signals.

Returns at most one pattern ``{patron, uso}`` or ``None``. Score per matched
tag = 1 / (how many patterns in the catalog share that tag) — same
specificity-weighting fix applied to PersonaFactsRetriever, for the same
reason: a broad tag shared by several patterns must not outweigh a narrow
tag unique to the right one. No embeddings.
"""

from __future__ import annotations

from collections import Counter

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.ports import PersonaCatalogProvider


def _norm(token: object) -> str:
    return str(token).strip().lower()


class VoicePatternsRetriever:
    """Fetch at most one voice pattern matching emotion/intent/topics."""

    def __init__(
        self,
        patterns: list[dict] | None = None,
        *,
        persona_catalog_provider: PersonaCatalogProvider | None = None,
    ) -> None:
        self._provider = persona_catalog_provider
        self._last_patterns: object = None
        self._patterns: list[dict] = []
        self._tag_freq: Counter[str] = Counter()
        self._set_patterns(patterns or [])

    def _set_patterns(self, patterns: list[dict]) -> None:
        """(Re)build internal state from a voice_patterns slice."""
        self._patterns = list(patterns)
        self._tag_freq = Counter()
        for pattern in self._patterns:
            for tag in set(_norm(t) for t in pattern.get("tags", [])):
                self._tag_freq[tag] += 1

    async def _maybe_refresh(self) -> None:
        """Pull a fresh slice from the live catalog when it changed (by identity)."""
        if self._provider is None:
            return
        catalog = await self._provider.get_catalog()
        if catalog is None:
            return
        slice_ = catalog.get("voice_patterns")
        if slice_ is not self._last_patterns:
            self._last_patterns = slice_
            self._set_patterns(slice_ or [])

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> dict[str, str] | None:
        _ = turn  # match is comprehension-driven only
        await self._maybe_refresh()
        signals = {
            _norm(comprehension.emotion),
            _norm(comprehension.intent),
            *(_norm(t) for t in comprehension.topics if str(t).strip()),
        }
        best: dict[str, str] | None = None
        best_score = 0.0
        for pattern in self._patterns:
            tags = pattern.get("tags") or []
            if not isinstance(tags, list):
                tags = [tags]
            tag_set = {_norm(t) for t in tags if str(t).strip()}
            inter = signals & tag_set
            if not inter:
                continue
            score = sum(1.0 / self._tag_freq[t] for t in inter)
            if score > best_score:
                best_score = score
                best = {
                    "patron": str(pattern["patron"]),
                    "uso": str(pattern["uso"]),
                }
        return best


__all__ = ["VoicePatternsRetriever"]
