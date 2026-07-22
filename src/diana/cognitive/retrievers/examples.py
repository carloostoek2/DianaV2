"""STUB retriever for knowledge.examples — always None in F1.

Must never read VIP personal recall storage (BR-15 / anti-contamination).
"""

from __future__ import annotations

from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn


class ExamplesRetriever:
    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None:
        _ = turn, comprehension
        return None
