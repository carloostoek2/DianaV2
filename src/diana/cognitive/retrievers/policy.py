"""PolicyRetriever — active policy lookup by embedding similarity.

Returns ``None`` when no embedding_service / repo is provided (stub backward
compatibility with F1 callers).

Pure cognitive module: does NOT import from ``diana.infrastructure``.
"""

from __future__ import annotations

import logging
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn

logger = logging.getLogger(__name__)

DEFAULT_POLICY_THRESHOLD = 0.8
DEFAULT_POLICY_LIMIT = 5


class PolicyRetriever:
    """Active policy retriever scoped by embedding similarity and VIP segment."""

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
        """Return formatted active policies, or None if unavailable.

        Uses ``comprehension`` fields to determine VIP segment/scope for
        policy matching. Defaults to no scope filter when segment is unknown.
        """
        if self._repo is None or self._embed is None:
            logger.debug("PolicyRetriever: deps not configured, returning None")
            return None  # stub compat

        embedding = await self._embed.embed(turn.text)

        # Scope filtering is reserved for future use (when Comprehension has segment fields).
        vip_segment: str | None = None

        rows = await self._repo.find_active_by_similarity(
            embedding,
            threshold=DEFAULT_POLICY_THRESHOLD,
            scope=vip_segment,
            limit=DEFAULT_POLICY_LIMIT,
        )
        if not rows:
            logger.debug("PolicyRetriever: no matching policies")
            return []

        out: list[str] = []
        for row in rows:
            out.append(f"Trigger: {row['trigger_description']} | Rule: {row['rule']}")
        return out


__all__ = ["PolicyRetriever"]
