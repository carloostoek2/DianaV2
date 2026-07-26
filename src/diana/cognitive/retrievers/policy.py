"""PolicyRetriever — static soft policies + optional embedding similarity.

Returns ``None`` when no embedding_service / repo is provided AND no static
catalog is configured (stub backward compatibility with F1 callers).

When ``static_policies`` is present, matches by tema ∩ (topics ∪ {intent}).
DB/pgvector hits (when deps configured) are appended after static; de-duplicated
by exact rule text.

Pure cognitive module: does NOT import from ``diana.infrastructure``.
"""

from __future__ import annotations

import logging
from typing import Any

from diana.cognitive.models import Comprehension, IncomingTurn

logger = logging.getLogger(__name__)

DEFAULT_POLICY_THRESHOLD = 0.8
DEFAULT_POLICY_LIMIT = 5


def _as_tema_list(tema: Any) -> list[str]:
    if isinstance(tema, list):
        return [str(t) for t in tema]
    if tema is None:
        return []
    return [str(tema)]


def _rule_text_from_formatted(line: str) -> str:
    marker = "| Rule: "
    if marker in line:
        return line.split(marker, 1)[1]
    return line


class PolicyRetriever:
    """Active policy retriever: static tema match + optional embedding path."""

    def __init__(
        self,
        *,
        embedding_service: Any = None,
        repo: Any = None,
        static_policies: list[dict] | None = None,
    ) -> None:
        self._embed = embedding_service
        self._repo = repo
        self._static = list(static_policies) if static_policies else None

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None:
        """Return formatted policies, empty list, or None if unavailable."""
        has_static = self._static is not None
        has_db = self._repo is not None and self._embed is not None

        if not has_static and not has_db:
            logger.debug("PolicyRetriever: deps not configured, returning None")
            return None  # stub compat

        out: list[str] = []
        seen_rules: list[str] = []

        if has_static:
            signals = set(comprehension.topics) | {comprehension.intent}
            for policy in self._static or []:
                temas = _as_tema_list(policy.get("tema"))
                if not (signals & set(temas)):
                    continue
                pid = policy.get("id") or (temas[0] if temas else "policy")
                regla = str(policy.get("regla") or "")
                line = f"Trigger: {pid} | Rule: {regla}"
                rule_key = _rule_text_from_formatted(line)
                if rule_key in seen_rules:
                    continue
                seen_rules.append(rule_key)
                out.append(line)

        if has_db:
            embedding = await self._embed.embed(turn.text)
            vip_segment: str | None = None
            rows = await self._repo.find_active_by_similarity(
                embedding,
                threshold=DEFAULT_POLICY_THRESHOLD,
                scope=vip_segment,
                limit=DEFAULT_POLICY_LIMIT,
            )
            if not rows and not out and has_static:
                # static present, no static hits, no DB rows → []
                return out
            if not rows and not has_static:
                logger.debug("PolicyRetriever: no matching policies")
                return []
            for row in rows or []:
                line = f"Trigger: {row['trigger_description']} | Rule: {row['rule']}"
                rule_key = _rule_text_from_formatted(line)
                if rule_key in seen_rules:
                    continue
                seen_rules.append(rule_key)
                out.append(line)

        # Static-only with no match → [] (not None)
        return out


__all__ = ["PolicyRetriever"]
