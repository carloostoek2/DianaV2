"""ContextStoreService — post-turn persistence of interpreted temporal context.

Implements the F2 design that left the ``contexts`` table unwired
(REQ-MEM-06): after a terminal turn, the chat's conversation state is
*interpreted* (pure H.3 logic shared with the in-pipeline ``ContextRetriever``)
and persisted with an embedding and an expiry, so later turns can read the
interpreted facts from the table instead of re-deriving everything from raw
history.

Best-effort strict (same pattern as ``MemoryExtractionService``): a failure
here NEVER propagates to the already-completed turn; flag OFF → no-op.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from diana.cognitive.retrievers.context import interpret_context

logger = logging.getLogger(__name__)


class ContextStoreService:
    """Post-turn writer for the ``contexts`` table (flag-gated, best-effort)."""

    def __init__(
        self,
        *,
        feature_context_enabled: bool,
        embedder: Any,
        history: Any,
        contexts: Any,
        turns: Any,
        ttl_hours: int = 24,
    ) -> None:
        """``contexts`` must expose ``insert(chat_id, content, embedding, expires_at, vip_id)``.

        ``turns`` must expose ``get(turn_id)`` (for chat_id/vip_id resolution),
        ``history`` ``get_recent(chat_id, limit)`` and ``embedder`` ``embed(text)``.
        """
        self._enabled = bool(feature_context_enabled)
        self._embedder = embedder
        self._history = history
        self._contexts = contexts
        self._turns = turns
        self._ttl = timedelta(hours=max(1, int(ttl_hours)))

    async def record_post_turn(self, turn_id: UUID) -> bool:
        """Interpret + persist the chat context after a terminal turn.

        Returns True when a snapshot was written, False when skipped
        (flag off, unresolved turn, empty interpretation) — NEVER raises.
        """
        if not self._enabled:
            return False
        try:
            return await self._record(turn_id)
        except Exception:
            logger.exception(
                "context_store_failed",
                extra={"turn_id": str(turn_id)},
            )
            return False

    async def _record(self, turn_id: UUID) -> bool:
        turn = await self._turns.get(turn_id)
        if turn is None:
            logger.debug("context_store_skipped_no_turn", extra={"turn_id": str(turn_id)})
            return False
        chat_id = getattr(turn, "chat_id", None)
        vip_id = getattr(turn, "vip_id", None)
        if chat_id is None:
            return False

        messages = await self._history.get_recent(chat_id, limit=20)
        interpreted = interpret_context(messages)
        if not interpreted:
            return False

        # The snapshot body is the interpreted facts; the embedding covers
        # the whole interpreted payload so similarity queries over past
        # conversation states work (same 384-dim space as memory/examples).
        body = {
            "tipo": "interpretado",
            "hechos": interpreted,
        }
        import json

        embedding = await self._embedder.embed(
            json.dumps(interpreted, ensure_ascii=False, default=str)
        )
        await self._contexts.insert(
            chat_id=chat_id,
            content=body,
            embedding=embedding,
            expires_at=datetime.now(UTC) + self._ttl,
            vip_id=vip_id,
        )
        logger.info(
            "context_store_written",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "ttl_hours": self._ttl.total_seconds() // 3600,
            },
        )
        return True


__all__ = ["ContextStoreService"]
