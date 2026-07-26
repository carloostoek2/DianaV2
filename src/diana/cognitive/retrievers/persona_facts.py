"""PersonaFactsRetriever — static catalog match by tema ∩ topics/intent.

Returns a single atomic fact ``{hecho, tema}`` or ``None``. Never emits
``nota_privada``. No embeddings; pure in-memory set intersection.

When multiple facts match, prefer the largest intersection size; ties keep
catalog list order.
"""

from __future__ import annotations

from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn


def _norm(token: Any) -> str:
    return str(token).strip().lower()


def _as_tema_list(tema: Any) -> list[str]:
    if isinstance(tema, list):
        return [_norm(t) for t in tema if str(t).strip()]
    if tema is None:
        return []
    token = _norm(tema)
    return [token] if token else []


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
        topics = {_norm(t) for t in comprehension.topics if str(t).strip()} | {
            _norm(comprehension.intent)
        }

        best: dict[str, str] | None = None
        best_score = 0
        for fact in self._facts:
            temas = _as_tema_list(fact.get("tema"))
            if not temas:
                continue
            inter = topics & set(temas)
            score = len(inter)
            if score > best_score:
                best_score = score
                # Prefer first tema that is in the intersection (stable within fact).
                match_tema = next((t for t in temas if t in inter), temas[0])
                best = {
                    "hecho": str(fact["hecho"]),
                    "tema": match_tema,
                }
        return best


__all__ = ["PersonaFactsRetriever"]
