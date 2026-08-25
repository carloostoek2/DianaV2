"""ProfileRetriever — VIP profile for the Generator (knowledge.profile).

Two sources, merged into one profile block:

- ``synthesis_repo`` (REAL): the Evo-Agente synthesized profile
  (``vip_profile``) — ``stable_traits`` + ``recent_trend`` with sensitive
  traits filtered out (a trait flagged in ``sensitivities`` never reaches the
  prompt, mirroring the memories visibility rule).
- ``repo`` (manual): the owner-curated ``profiles`` vector table
  (facts/notes set via ``/vip_profile``).

When ``synthesis_repo`` is absent the retriever keeps the legacy manual-only
shape ``{"tipo", "content"}`` (backward-compatible with F1 callers and tests).

Anti-contamination (BR-15): never call a repo when ``turn.vip_id is None``.
Pure cognitive module: does NOT import from ``diana.infrastructure``.
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


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from a dict or a duck-typed object (VipProfileRecord)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize(label: Any) -> str:
    """Collapse a trait key/label to a comparable token (snake_case aware)."""
    return " ".join(str(label).lower().replace("_", " ").split())


def _sensitive_labels(sensitivities: list) -> set[str]:
    """Normalized labels of the traits the synthesis marked sensitive."""
    labels: list[str] = []
    for item in sensitivities or []:
        label = _normalize(_get(item, "trait", ""))
        if label:
            labels.append(label)
    return set(labels)


def _filter_sensitive(traits: dict, sensitive_labels: set[str]) -> dict:
    """Drop traits whose key (or ``trait`` label) is flagged sensitive."""
    if not traits:
        return {}
    out: dict[str, Any] = {}
    for key, value in traits.items():
        if _normalize(key) in sensitive_labels:
            continue
        if isinstance(value, dict):
            value_label = _normalize(value.get("trait", ""))
            if value_label in sensitive_labels or any(
                label in value_label for label in sensitive_labels
            ):
                continue
        out[key] = value
    return out


class ProfileRetriever:
    """VIP profile reader: synthesized (vip_profile) + manual (profiles)."""

    def __init__(self, *, repo: Any = None, synthesis_repo: Any = None) -> None:
        self._repo = repo
        self._synthesis_repo = synthesis_repo

    async def fetch(
        self,
        turn: IncomingTurn,
        comprehension: Comprehension,
    ) -> Any | None:
        """Return the merged profile, or None if nothing visible is available.

        ``comprehension`` is unused (protocol parity only); filter is VIP PK.
        """
        _ = comprehension
        if self._repo is None and self._synthesis_repo is None:
            logger.debug("ProfileRetriever: no repos configured, returning None")
            return None

        vip_id = turn.vip_id
        if vip_id is None:
            logger.debug("ProfileRetriever: vip_id is None, returning None")
            return None

        if self._synthesis_repo is None:
            return await self._fetch_manual_legacy(vip_id)

        synthesis = await self._fetch_synthesis(vip_id)
        manual = await self._fetch_manual(vip_id)

        content: dict[str, Any] = {}
        if synthesis is not None:
            content["sintesis"] = synthesis
        if manual is not None:
            content["manual"] = manual
        if not content:
            return None
        return {"tipo": "profile", "content": content}

    async def _fetch_manual_legacy(self, vip_id: Any) -> dict | None:
        """Legacy path (no synthesis repo): ``{"tipo", "content"}`` or None."""
        row = await self._repo.get_by_vip_id(vip_id)
        if row is None:
            logger.debug("ProfileRetriever: miss for vip_id=%s", vip_id)
            return None
        content = row.get("content")
        if _is_null_like_content(content):
            logger.debug("ProfileRetriever: empty content for vip_id=%s", vip_id)
            return None
        if isinstance(content, dict) and ("facts" in content or "notes" in content):
            other = {k: v for k, v in content.items() if k not in ("facts", "notes")}
            if not other:
                content = normalize_content(content)
        return {"tipo": row["tipo"], "content": content}

    async def _fetch_manual(self, vip_id: Any) -> dict | None:
        """Manual profile content (normalized) or None (no repo / miss / hollow)."""
        if self._repo is None:
            return None
        row = await self._repo.get_by_vip_id(vip_id)
        if row is None:
            logger.debug("ProfileRetriever: manual miss for vip_id=%s", vip_id)
            return None
        content = row.get("content")
        if _is_null_like_content(content):
            logger.debug("ProfileRetriever: manual empty content for vip_id=%s", vip_id)
            return None
        if isinstance(content, dict) and ("facts" in content or "notes" in content):
            other = {k: v for k, v in content.items() if k not in ("facts", "notes")}
            if not other:
                content = normalize_content(content)
        return content

    async def _fetch_synthesis(self, vip_id: Any) -> dict | None:
        """Synthesized profile (filtered) or None (no repo / miss / hollow)."""
        if self._synthesis_repo is None:
            return None
        record = await self._synthesis_repo.get_by_vip(vip_id)
        if record is None:
            logger.debug("ProfileRetriever: synthesis miss for vip_id=%s", vip_id)
            return None

        sensitive = _sensitive_labels(_get(record, "sensitivities", []) or [])
        stable = _filter_sensitive(_get(record, "stable_traits", {}) or {}, sensitive)
        trend = _filter_sensitive(_get(record, "recent_trend", {}) or {}, sensitive)

        out: dict[str, Any] = {}
        if stable:
            out["stable_traits"] = stable
        if trend:
            out["recent_trend"] = trend
        if not out:
            logger.debug("ProfileRetriever: synthesis hollow for vip_id=%s", vip_id)
            return None
        return out


__all__ = ["ProfileRetriever"]
