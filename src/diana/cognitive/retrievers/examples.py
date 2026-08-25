"""ExamplesRetriever — curated example pool (BR-15: never reads VIP memory).

Returns ``None`` when no embedding_service / repo is provided (stub backward
compatibility with F1 callers).

CRITICAL: This module must NEVER import from ``memory``, ``memories``, or any
VIP personal recall module (AST gate enforcement).

Pure cognitive module: does NOT import from ``diana.infrastructure``.
"""

from __future__ import annotations

import logging
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn

logger = logging.getLogger(__name__)

# Calibrated: the best example match scored ~0.508 for a real turn (the old 0.7
# gate never fired). Set below the measured 0.5077 so the strict `>` gate
# admits it.
DEFAULT_EXAMPLES_THRESHOLD = 0.50
DEFAULT_EXAMPLES_LIMIT = 5


class ExamplesRetriever:
    """Curated example retriever. Always appends a matching counter-example when one exists."""

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
        """Return formatted examples, or None if unavailable.

        Always appends a matching counter-example when one exists.
        """
        if self._repo is None or self._embed is None:
            logger.debug("ExamplesRetriever: deps not configured, returning None")
            return None  # stub compat

        embedding = await self._embed.embed(turn.text)

        rows = await self._repo.find_by_similarity(
            embedding,
            threshold=DEFAULT_EXAMPLES_THRESHOLD,
            limit=DEFAULT_EXAMPLES_LIMIT,
            counter_example=False,
            vip_id=turn.vip_id,
        )

        out: list[str] = []
        for row in rows:
            out.append(
                f"Turn: {row['turn_text']} | Draft: {row['draft_text']} | Corrected: {row['corrected_text']}"
            )

        counter_rows = await self._repo.find_by_similarity(
            embedding,
            threshold=DEFAULT_EXAMPLES_THRESHOLD,
            limit=1,
            counter_example=True,
            vip_id=turn.vip_id,
        )
        if counter_rows:
            logger.debug("ExamplesRetriever: counter-example appended")
            cr = counter_rows[0]
            out.append(
                f"[COUNTER-EXAMPLE] Turn: {cr['turn_text']} | Draft: {cr['draft_text']} | Corrected: {cr['corrected_text']}"
            )

        return out


__all__ = ["ExamplesRetriever"]
