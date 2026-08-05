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
from diana.cognitive.ports import PersonaCatalogProvider


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

    def __init__(
        self,
        facts: list[dict] | None = None,
        *,
        persona_catalog_provider: PersonaCatalogProvider | None = None,
    ) -> None:
        self._provider = persona_catalog_provider
        self._last_facts: dict[str, object] = {}
        self._facts: dict[str, list[dict]] = {}
        self._tag_freq: dict[str, Counter[str]] = {}
        self._set_facts("vip", facts or [])

    def _set_facts(self, channel_type: str, facts: list[dict]) -> None:
        """(Re)build per-channel state from a facts slice (identity-refresh aware)."""
        self._facts[channel_type] = list(facts)
        # Tag frequency across the channel's whole catalog — drives the
        # specificity weighting (1 / freq) used at match time.
        self._tag_freq[channel_type] = Counter()
        for fact in self._facts[channel_type]:
            for tema in set(_as_tema_list(fact.get("tema"))):
                self._tag_freq[channel_type][tema] += 1

    async def _maybe_refresh(self, channel_type: str) -> None:
        """Pull a fresh per-channel slice from the live catalog when it changed.

        The identity cache is keyed by channel so switching channels
        re-refreshes (an atencion turn must never reuse the VIP slice). A
        ``None`` slice (key missing) or a non-list value keeps the last good
        state — the provider's validation contract already guarantees lists,
        but a corrupt row must never wipe the retriever.
        """
        if self._provider is None:
            return
        catalog = await self._provider.get_catalog(channel_type=channel_type)
        if catalog is None:
            return
        slice_ = catalog.get("persona_facts")
        if slice_ is None:
            return
        if not isinstance(slice_, list):
            return
        if self._last_facts.get(channel_type) is not slice_:
            self._last_facts[channel_type] = slice_
            self._set_facts(channel_type, slice_)

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> dict[str, str] | None:
        _ = turn  # match is comprehension-driven only
        await self._maybe_refresh(turn.channel_type)
        facts = self._facts.get(turn.channel_type)
        if facts is None:
            return None  # channel never populated → no fact, never VIP data
        tag_freq = self._tag_freq[turn.channel_type]
        topics = {_norm(t) for t in comprehension.topics if str(t).strip()} | {
            _norm(comprehension.intent)
        }

        best: dict[str, str] | None = None
        best_score = 0.0
        for fact in facts:
            temas = _as_tema_list(fact.get("tema"))
            if not temas:
                continue
            inter = topics & set(temas)
            if not inter:
                continue
            score = sum(1.0 / tag_freq[t] for t in inter)
            if score > best_score:
                best_score = score
                # Prefer the matched tag with the highest individual weight
                # (most specific) as the reported `tema`, not just the first.
                match_tema = max(inter, key=lambda t: 1.0 / tag_freq[t])
                best = {
                    "hecho": str(fact["hecho"]),
                    "tema": match_tema,
                }
        return best


__all__ = ["PersonaFactsRetriever"]
