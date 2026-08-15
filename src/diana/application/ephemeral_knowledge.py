"""Ephemeral event inject — application-side KnowledgeAugmenter.

Cognitive only sees the Protocol; this module owns EphemeralEventStore coupling
and the composite used to chain augmenters in wiring.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from diana.application.ports import EphemeralEventStore
from diana.cognitive.models import IncomingTurn


class EphemeralKnowledgeAugmenter:
    """Inject owner-injected time-bounded events into ``knowledge.ephemeral``.

    Injects only when at least one event is active at ``clock()``; otherwise
    returns ``retrieved`` untouched. Never mutates the input map — on a hit it
    returns a shallow copy with the extra key.
    """

    def __init__(
        self, store: EphemeralEventStore, clock: Callable[[], datetime]
    ) -> None:
        self._store = store
        self._clock = clock

    async def augment_retrieved(
        self,
        turn: IncomingTurn,
        retrieved: dict[str, Any | None],
    ) -> dict[str, Any | None]:
        events = await self._store.find_active_at(self._clock())
        if not events:
            return retrieved
        out = dict(retrieved)
        out["knowledge.ephemeral"] = {"eventos": [e.body for e in events]}
        return out


class CompositeKnowledgeAugmenter:
    """Apply a chain of augmenters in order, threading the returned dict.

    Each augmenter's output feeds the next; each may return ``retrieved``
    unchanged. All are additive over ``knowledge.*`` keys, so chaining is safe.
    """

    def __init__(self, augmenters: list[Any]) -> None:
        self._augmenters = augmenters

    async def augment_retrieved(
        self,
        turn: IncomingTurn,
        retrieved: dict[str, Any | None],
    ) -> dict[str, Any | None]:
        out: dict[str, Any | None] = retrieved
        for augmenter in self._augmenters:
            out = await augmenter.augment_retrieved(turn, out)
        return out


__all__ = ["CompositeKnowledgeAugmenter", "EphemeralKnowledgeAugmenter"]
