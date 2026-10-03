"""Shared tag/tema normalization for persona facts (panel write + retriever match).

One function, used on BOTH sides so owner-typed temas ("Motivación personal")
and Analyst-emitted topics ("motivacion_personal") compare equal, and so data
already stored in ``persona_versions`` (raw temas) keeps matching without a
migration — the retriever normalizes stored values at read time.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
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


_NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)


def tokenize_words(text: Any) -> list[str]:
    """Split free text into normalized whole-word tokens.

    Unlike :func:`normalize_tag` (which keeps punctuation inside the tag),
    this strips ALL punctuation — including ``¿ ? ¡ !`` — plus accents and
    case, then splits on anything that is not a letter/digit:
    ``"¿Quién es Lucien?"`` → ``["quien", "es", "lucien"]``.
    Used for deterministic alias n-gram matching (``knowledge.operacion``).
    """
    if text is None:
        return []
    raw = unicodedata.normalize("NFKD", str(text))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch)).lower()
    return [tok for tok in _NON_WORD_RE.split(raw) if tok]


def _catalog_section_tags(
    catalog: dict[str, Any] | None, section: str, field: str, limit: int | None
) -> list[str]:
    """Distinct normalized values of ``field`` across ``catalog[section]``.

    Pure: works on a catalog already resolved for ONE channel (the caller
    guarantees isolation). Catalog order, first appearance wins; any
    malformed shape yields ``[]`` / is skipped. ``limit=None`` → no cap.
    """
    if not isinstance(catalog, dict):
        return []
    items = catalog.get(section)
    if not isinstance(items, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for tag in normalize_tags(item.get(field)):
            if tag not in seen:
                seen.add(tag)
                out.append(tag)
                if limit is not None and len(out) >= limit:
                    return out
    return out


def catalog_fact_topics(
    catalog: dict[str, Any] | None, *, limit: int | None = 60
) -> list[str]:
    """Distinct normalized temas declared by ``persona_facts`` in a catalog.

    Used to tell the Analyst which temas the ACTIVE catalog (per channel) can
    actually answer, so owner-added temas are reachable. Order is catalog
    order. Default cap 60 kept for backward compatibility; ``limit=None`` →
    uncapped (the Director passes None: the prompt budget is applied by the
    Analyst with :func:`fair_share_limits`).
    """
    return _catalog_section_tags(catalog, "persona_facts", "tema", limit)


def catalog_policy_topics(
    catalog: dict[str, Any] | None, *, limit: int | None = None
) -> list[str]:
    """Distinct normalized ``tema`` values of ``policies`` (Políticas), uncapped by default."""
    return _catalog_section_tags(catalog, "policies", "tema", limit)


def catalog_pattern_tags(
    catalog: dict[str, Any] | None, *, limit: int | None = None
) -> list[str]:
    """Distinct normalized ``tags`` of ``voice_patterns`` (Patrones de voz), uncapped by default."""
    return _catalog_section_tags(catalog, "voice_patterns", "tags", limit)


def fair_share_limits(sizes: Sequence[int], budget: int) -> list[int]:
    """Split ``budget`` slots fairly among groups of ``sizes`` items (max-min).

    Pure and deterministic (same input → same output). Algorithm
    ("water-filling"):

    1. Groups with size <= 0 are absent and get 0.
    2. ``share, extra = divmod(remaining, n_active)``.
    3. Every active group whose size <= ``share`` gets its full size; its
       unused slots return to ``remaining``; drop it from the active set and
       go back to 2.
    4. If no active group fits, each gets ``share`` and the first ``extra``
       active groups **in input order** get one more slot; stop.

    Guarantees: ``limits[i] <= sizes[i]``; ``sum(limits) == min(budget,
    sum(sizes))``; each present group gets at least
    ``min(size, budget // n_present)``; if everything fits, nothing is cut;
    a single present group gets the whole budget. Ties are resolved only by
    input order (for the remainder slots).
    """
    if budget < 0:
        raise ValueError("budget must be >= 0")
    clean = [max(int(s), 0) for s in sizes]
    limits = [0] * len(clean)
    active = [i for i, s in enumerate(clean) if s > 0]
    remaining = int(budget)
    while active and remaining > 0:
        share, extra = divmod(remaining, len(active))
        fits = [i for i in active if clean[i] <= share]
        if fits:
            for i in fits:
                limits[i] = clean[i]
                remaining -= clean[i]
            active = [i for i in active if i not in fits]
            continue
        for rank, i in enumerate(active):
            limits[i] = share + (1 if rank < extra else 0)
        remaining = 0
    return limits


__all__ = [
    "catalog_fact_topics",
    "catalog_pattern_tags",
    "catalog_policy_topics",
    "fair_share_limits",
    "normalize_tag",
    "normalize_tags",
    "tokenize_words",
]
