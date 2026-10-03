"""Policy embedding retry + zero-vector marker repair (G-D1).

hardener/persona-reglas ítem 3 (D2). A policy whose embedding could not be
computed is still persisted (fail-open) with the zero-vector marker
(``policies.ZERO_EMBEDDING``) and a ``policy_embedding_pending`` WARNING.
``PolicyEmbeddingRepairService`` re-embeds those rows later, at boot and
periodically (driven by ``jobs.embedding_warmup.EmbeddingWarmupJob``), using the
exact same text the insert path uses. It never writes a zero vector.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("diana.application")


def policy_embedding_text(trigger: str, rule: str) -> str:
    """Text fingerprinted for a policy (same at insert and at repair)."""
    return f"{trigger}\n{rule}"


async def embed_policy_text(
    embedder: Any, text: str, *, attempts: int = 2
) -> list[float] | None:
    """G-D1 (a): retry with warmup. None → the caller writes the zero marker + WARNING."""
    if embedder is None or not text:
        return None
    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1 and callable(getattr(embedder, "warmup", None)):
                await embedder.warmup()
            return await embedder.embed(text)
        except Exception:
            logger.warning(
                "policy_embed_attempt_failed",
                extra={"attempt": attempt},
                exc_info=True,
            )
    return None


class PolicyEmbeddingRepairService:
    """Re-embed active policies that still carry the zero-vector marker."""

    def __init__(self, policies_repo: Any, embedder: Any, *, attempts: int = 2) -> None:
        self._repo = policies_repo
        self._embedder = embedder
        self._attempts = attempts

    async def repair_once(self, *, limit: int = 50) -> dict[str, int]:
        rows = await self._repo.list_active_zero_embedding(limit=limit)
        repaired = failed = 0
        for row in rows:
            emb = await embed_policy_text(
                self._embedder,
                policy_embedding_text(row.trigger_description, row.rule),
                attempts=self._attempts,
            )
            if emb is None or not any(emb):  # never write a zero vector
                failed += 1
                continue
            await self._repo.set_embedding(row.id, emb)
            repaired += 1
        stats = {"found": len(rows), "repaired": repaired, "failed": failed}
        logger.log(
            logging.WARNING if failed else logging.INFO,
            "policy_embedding_repair",
            extra=stats,
        )
        return stats


__all__ = [
    "PolicyEmbeddingRepairService",
    "embed_policy_text",
    "policy_embedding_text",
]
