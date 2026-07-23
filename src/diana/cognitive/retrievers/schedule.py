"""Half-registered MVP seat for knowledge.schedule (Anexo H.3).

``fuente=no_implementado``; ``fetch`` always returns None.
Still resolvable so Planner may request it without mid-turn KeyError.
"""

from __future__ import annotations

from diana.cognitive.models import Comprehension, IncomingTurn


class ScheduleRetriever:
    """Half-registered MVP seat (Anexo H.3). fuente=no_implementado; always None."""

    fuente: str = "no_implementado"

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> None:
        _ = turn, comprehension
        return None
