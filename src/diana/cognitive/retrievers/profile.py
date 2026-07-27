"""ProfileRetriever — VIP permanent profile by PK (knowledge.profile).

REAL when a duck-typed ``repo`` with ``get_by_vip_id`` is injected; otherwise
returns ``None`` (F1 stub compatibility).

Anti-contamination (BR-15): never call the repo when ``turn.vip_id is None``.
Pure cognitive module: does NOT import from ``diana.infrastructure``.
"""

from __future__ import annotations

import logging
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn

logger = logging.getLogger(__name__)


def _is_null_like_content(content: Any) -> bool:
    """Mirror ContextBuilder null-like rules for the content payload only.

    Outer hit shape is always ``{"tipo", "content"}``; empty content must
    collapse to fetch ``None`` so D.5 does not emit a hollow profile envelope.

    Hollow schema envelope (Option A): ``{"facts": {}, "notes": []}`` (or only
    one of those keys empty, with no other top-level payload) is null-like.
    Legacy flat shapes like ``{"fact": "prefers morning"}`` remain hits.
    """
    if content is None:
        return True
    if isinstance(content, (list, dict, tuple, set)) and len(content) == 0:
        return True
    if isinstance(content, str) and not content.strip():
        return True
    if isinstance(content, dict):
        facts = content.get("facts")
        notes = content.get("notes")
        facts_empty = facts is None or (isinstance(facts, dict) and len(facts) == 0)
        notes_empty = notes is None or (isinstance(notes, list) and len(notes) == 0)
        if facts_empty and notes_empty:
            other = {k: v for k, v in content.items() if k not in ("facts", "notes")}
            if not other:
                return True
    return False


class ProfileRetriever:
    """VIP-scoped permanent profile reader (PK lookup, not similarity)."""

    def __init__(self, *, repo: Any = None) -> None:
        self._repo = repo

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None:
        """Return ``{"tipo", "content"}`` for the VIP, or None if unavailable.

        ``comprehension`` is unused (protocol parity only); filter is VIP PK.
        """
        _ = comprehension
        if self._repo is None:
            logger.debug("ProfileRetriever: repo not configured, returning None")
            return None

        vip_id = turn.vip_id
        if vip_id is None:
            logger.debug("ProfileRetriever: vip_id is None, returning None")
            return None

        row = await self._repo.get_by_vip_id(vip_id)
        if row is None:
            logger.debug("ProfileRetriever: miss for vip_id=%s", vip_id)
            return None

        content = row.get("content")
        if _is_null_like_content(content):
            logger.debug("ProfileRetriever: empty content for vip_id=%s", vip_id)
            return None

        return {"tipo": row["tipo"], "content": content}


__all__ = ["ProfileRetriever"]
