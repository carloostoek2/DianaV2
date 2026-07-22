"""STUB retriever for knowledge.profile — always None in F1."""

from __future__ import annotations

from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn


class ProfileRetriever:
    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None:
        _ = turn, comprehension
        return None
