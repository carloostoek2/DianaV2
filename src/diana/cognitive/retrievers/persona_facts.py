"""PersonaFactsRetriever — static catalog match by tema ∩ topics/intent.

Returns a single atomic fact ``{hecho, tema}`` or ``None``. Never emits
``nota_privada``. No embeddings; pure in-memory set intersection, weighted
by tag specificity.

Score per matched tag = 1 / (how many facts in the catalog share that tag).
A generic tag shared by many facts (e.g. "estudios") barely moves the score;
a tag unique to one fact (e.g. "motivacion_personal") dominates. This avoids
ties where a broad shared tag outweighs the one specific tag that actually
identifies the right fact — plain intersection-count matching picked the
wrong fact in production for "qué te llevó a estudiar psicología?" because
both the trajectory fact and the motivation fact share "estudios".
"""

from __future__ import annotations

from collections import Counter
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
        # Tag frequency across the whole catalog, computed once — drives
        # the specificity weighting (1 / freq) used at match time.
        self._tag_freq: Counter[str] = Counter()
        for fact in self._facts:
            for tema in set(_as_tema_list(fact.get("tema"))):
                self._tag_freq[tema] += 1

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
        best_score = 0.0
        for fact in self._facts:
            temas = _as_tema_list(fact.get("tema"))
            if not temas:
                continue
            inter = topics & set(temas)
            if not inter:
                continue
            score = sum(1.0 / self._tag_freq[t] for t in inter)
            if score > best_score:
                best_score = score
                # Prefer the matched tag with the highest individual weight
                # (most specific) as the reported `tema`, not just the first.
                match_tema = max(inter, key=lambda t: 1.0 / self._tag_freq[t])
                best = {
                    "hecho": str(fact["hecho"]),
                    "tema": match_tema,
                }
        return best


__all__ = ["PersonaFactsRetriever"]
