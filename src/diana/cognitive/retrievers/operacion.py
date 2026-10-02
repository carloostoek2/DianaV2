"""OperacionRetriever — deterministic alias-triggered internal business facts.

Reads ONLY the live catalog of the turn's channel through the
``PersonaCatalogProvider`` (vip and atencion are isolated: the provider never
resolves VIP material for atencion). No static/constructor fallback: with no
provider or no catalog the capability yields nothing.

Emits only ``[{"hecho": ...}]`` — never ``id``, ``alias`` or ``nota_privada``.
The Director decides WHEN to request this capability (deterministic alias
match after the Analyst, flag-gated); this class only matches and formats.
"""

from __future__ import annotations

import logging

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.cognitive.operacion import (
    DEFAULT_MAX_OPERACION_FACTS,
    OperacionHit,
    match_operacion,
)
from diana.cognitive.ports import PersonaCatalogProvider

logger = logging.getLogger("diana.cognitive")


class OperacionRetriever:
    """Match ``turn.text`` against the channel's ``operacion`` aliases."""

    def __init__(
        self,
        *,
        persona_catalog_provider: PersonaCatalogProvider | None = None,
        max_items: int = DEFAULT_MAX_OPERACION_FACTS,
    ) -> None:
        if int(max_items) < 1:
            raise ValueError("max_items must be >= 1")
        self._provider = persona_catalog_provider
        self._max_items = int(max_items)

    async def match(self, turn: IncomingTurn) -> list[OperacionHit]:
        """Capped deterministic hits for this turn (fail-soft → ``[]``)."""
        if self._provider is None:
            return []
        try:
            catalog = await self._provider.get_catalog(turn.channel_type)
        except Exception:
            logger.warning(
                "operacion_catalog_read_failed",
                extra={"channel_type": turn.channel_type},
                exc_info=True,
            )
            return []
        return match_operacion(catalog, turn.text, limit=self._max_items)

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> list[dict[str, str]] | None:
        _ = comprehension  # alias match is text-driven, never Analyst-driven
        hits = await self.match(turn)
        if not hits:
            return None
        return [{"hecho": hit.hecho} for hit in hits]


__all__ = ["OperacionRetriever"]
