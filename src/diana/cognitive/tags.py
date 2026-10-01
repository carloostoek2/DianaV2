"""Shared tag/tema normalization for persona facts (panel write + retriever match).

One function, used on BOTH sides so owner-typed temas ("Motivación personal")
and Analyst-emitted topics ("motivacion_personal") compare equal, and so data
already stored in ``persona_versions`` (raw temas) keeps matching without a
migration — the retriever normalizes stored values at read time.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

_SEPARATORS_RE = re.compile(r"[\s\-‐-―]+")  # whitespace + ASCII/Unicode dashes
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def normalize_tag(value: Any) -> str:
    """Canonical tag form: no accents, lowercase, spaces/hyphens → ``_``.

    ``"  Motivación   personal "`` → ``"motivacion_personal"``;
    ``"auto-cuidado"`` → ``"auto_cuidado"``; ``"Ñoño"`` → ``"nono"``.
    Leading/trailing separators are trimmed; ``None``/blank → ``""``.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower()
    text = _SEPARATORS_RE.sub("_", text)
    text = _MULTI_UNDERSCORE_RE.sub("_", text)
    return text.strip("_")


def normalize_tags(values: Any) -> list[str]:
    """Normalize a tema list (or a single scalar tema), dropping blanks/dupes.

    Order of first appearance is preserved.
    """
    if values is None:
        return []
    items: Iterable[Any] = values if isinstance(values, (list, tuple, set)) else [values]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = normalize_tag(item)
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def catalog_fact_topics(catalog: dict[str, Any] | None, *, limit: int = 60) -> list[str]:
    """Distinct normalized temas declared by ``persona_facts`` in a catalog.

    Used to tell the Analyst which temas the ACTIVE catalog (per channel) can
    actually answer, so owner-added temas are reachable. Capped to keep the
    Analyst prompt small; order is catalog order.
    """
    if not isinstance(catalog, dict):
        return []
    facts = catalog.get("persona_facts")
    if not isinstance(facts, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        for tag in normalize_tags(fact.get("tema")):
            if tag not in seen:
                seen.add(tag)
                out.append(tag)
                if len(out) >= limit:
                    return out
    return out


__all__ = ["catalog_fact_topics", "normalize_tag", "normalize_tags"]
