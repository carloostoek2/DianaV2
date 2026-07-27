"""ProfileRetriever — VIP permanent profile by PK (knowledge.profile).

REAL when a duck-typed ``repo`` with ``get_by_vip_id`` is injected; otherwise
returns ``None`` (F1 stub compatibility).

Anti-contamination (BR-15): never call the repo when ``turn.vip_id is None``.
Pure cognitive module: does NOT import from ``diana.infrastructure``.
Hollow semantics: shared ``diana.profile_content.is_hollow_content``.
"""

from __future__ import annotations

import logging
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn
from diana.profile_content import is_hollow_content, normalize_content

logger = logging.getLogger(__name__)


def _is_null_like_content(content: Any) -> bool:
    """Null-like / hollow content collapses to fetch ``None``.

    Uses shared ``is_hollow_content`` (Option A + whitespace normalize +
    legacy flat non-empty still a hit). Generic empty collections/str still
    short-circuit first for ContextBuilder parity.
    """
    return is_hollow_content(content)


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
        Structured schema content is returned normalized so whitespace-only
        facts never reach the prompt envelope.
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

        # Prefer normalized schema when content is structured-only.
        # Keep legacy flat payloads as-is (normalize would drop them).
        if isinstance(content, dict) and (
            "facts" in content or "notes" in content
        ):
            other = {k: v for k, v in content.items() if k not in ("facts", "notes")}
            if not other:
                content = normalize_content(content)

        return {"tipo": row["tipo"], "content": content}


__all__ = ["ProfileRetriever"]
