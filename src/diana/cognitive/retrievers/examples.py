"""ExamplesRetriever — curated example pool (BR-15: never reads VIP memory).

Returns ``None`` when no embedding_service / repo is provided (stub backward
compatibility with F1 callers).

CRITICAL: This module must NEVER import from ``memory``, ``memories``, or any
VIP personal recall module (AST gate enforcement).

Pure cognitive module: does NOT import from ``diana.infrastructure``.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn

logger = logging.getLogger(__name__)

DEFAULT_EXAMPLES_THRESHOLD = 0.7
DEFAULT_EXAMPLES_LIMIT = 5


class ExamplesRetriever:
    """Curated example retriever. Optionally includes a counter-example (~10%)."""

    def __init__(
        self,
        *,
        embedding_service: Any = None,
        repo: Any = None,
        counter_example_chance: float = 0.1,
    ) -> None:
        self._embed = embedding_service
        self._repo = repo
        self._counter_example_chance = counter_example_chance

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None:
        """Return formatted examples, or None if unavailable.

        Optionally includes one counter-example at ~10% probability.
        """
        if self._repo is None or self._embed is None:
            return None  # stub compat

        embedding = await self._embed.embed(turn.text)

        rows = await self._repo.find_by_similarity(
            embedding,
            threshold=DEFAULT_EXAMPLES_THRESHOLD,
            limit=DEFAULT_EXAMPLES_LIMIT,
            counter_example=False,
        )
        if not rows:
            return []

        out: list[str] = []
        for row in rows:
            out.append(
                f"Turn: {row['turn_text']} | Draft: {row['draft_text']} | Corrected: {row['corrected_text']}"
            )

        # Optionally append a counter-example.
        if random.random() < self._counter_example_chance:
            counter_rows = await self._repo.find_by_similarity(
                embedding,
                threshold=DEFAULT_EXAMPLES_THRESHOLD,
                limit=1,
                counter_example=True,
            )
            if counter_rows:
                cr = counter_rows[0]
                out.append(
                    f"[COUNTER-EXAMPLE] Turn: {cr['turn_text']} | Draft: {cr['draft_text']} | Corrected: {cr['corrected_text']}"
                )

        return out


__all__ = ["ExamplesRetriever"]
