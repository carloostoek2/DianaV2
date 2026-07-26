"""PersonaFactsRetriever — static catalog match by tema ∩ topics/intent.

Returns a single atomic fact ``{hecho, tema}`` or ``None``. Never emits
``nota_privada``. No embeddings; pure in-memory set intersection.
"""

from __future__ import annotations

from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn


def _as_tema_list(tema: Any) -> list[str]:
    if isinstance(tema, list):
        return [str(t) for t in tema]
    if tema is None:
        return []
    return [str(tema)]


class PersonaFactsRetriever:
    """Fetch one persona fact whose tema intersects comprehension signals."""

    def __init__(self, facts: list[dict] | None = None) -> None:
        self._facts: list[dict] = list(facts or [])

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> dict[str, str] | None:
        _ = turn  # match is comprehension-driven only
        topics = set(comprehension.topics) | {comprehension.intent}
        for fact in self._facts:
            temas = _as_tema_list(fact.get("tema"))
            if topics & set(temas):
                return {
                    "hecho": str(fact["hecho"]),
                    "tema": temas[0],
                }
        return None


__all__ = ["PersonaFactsRetriever"]
