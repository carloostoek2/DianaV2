"""MemoryRetriever — VIP-scoped semantic memory (BR-15: every query has vip_id).

Returns ``None`` when no embedding_service / repo is provided (stub backward
compatibility with F1 callers).

Pure cognitive module: does NOT import from ``diana.infrastructure``.
"""

from __future__ import annotations

import logging
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_THRESHOLD = 0.75
DEFAULT_MEMORY_LIMIT = 5


class MemoryRetriever:
    """VIP-scoped semantic memory retriever.

    Anti-contamination (BR-15): every DB query includes ``WHERE vip_id = :vip_id``.
    Returns ``None`` when dependencies are not configured (F1-compatible stub).
    """

    def __init__(
        self,
        *,
        embedding_service: Any = None,
        repo: Any = None,
    ) -> None:
        self._embed = embedding_service
        self._repo = repo

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None:
        """Return formatted memories for the VIP, or None if unavailable.

        Returns:
            None: when deps are not configured, or VIP is unidentified.
            list[str]: formatted memory entries when matches are found.
            list[str]: empty list when no matches are found.
        """
        if self._repo is None or self._embed is None:
            logger.debug("MemoryRetriever: deps not configured, returning None")
            return None  # stub compat

        vip_id = turn.vip_id
        if vip_id is None:
            logger.debug("MemoryRetriever: vip_id is None, returning None")
            return None  # BR-15: unidentified VIP

        embedding = await self._embed.embed(turn.text)
        rows = await self._repo.find_by_vip_and_similarity(
            vip_id,
            embedding,
            threshold=DEFAULT_MEMORY_THRESHOLD,
            limit=DEFAULT_MEMORY_LIMIT,
        )
        if not rows:
            logger.debug("MemoryRetriever: no results for vip_id=%s", vip_id)
            return []

        out: list[str] = []
        for row in rows:
            category = row.get("category", "general")
            content = row.get("content", {})
            fact = content.get("fact", str(content))
            out.append(f"[{category}] {fact}")
        return out


__all__ = ["MemoryRetriever"]
