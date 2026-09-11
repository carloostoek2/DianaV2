"""Pure deterministic template matcher for short VIP replies (H6).

No I/O, no LLM. Cognitive Core only — does not import application/telegram/behavior.

Local ``_kw_hit`` is inspired by ``application.j4_triggers.match_keywords`` but is
stricter: multi-word phrases use non-word lookarounds on both sides (not bare
substring), so ``eres real`` does not match ``eres realmente`` / ``realista``.
"""


from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TemplateRule:
    """One fixed-template reply rule evaluated in list order."""

    id: str
    trigger_patterns: list[str]
    max_words: int | None
    response_pool: list[str]
    reason: str


# Historical saludo_constante shape (H6). Production no longer wires that
# TemplateRule pre-pipeline; the post-Analyst cut reuses the same lock so a
# mislabeled intent=saludar cannot canned-reply to real requests.
PURE_GREETING_MAX_WORDS = 4
PURE_GREETING_PATTERNS = (
    "hola",
    "holaa",
    "holis",
    "buenas",
    "buenos días",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "hey",
    "qué tal",
    "que tal",
)

# Allowed leftover tokens after stripping the greeting keyword (affection /
# vocatives only). Anything else ("como", "estas", "tu", "día", fillers)
# means the turn is a check-in or mixed content — fail open to full pipeline.
_PURE_GREETING_EXTRA_TOKENS = frozenset(
    {
        "amor",
        "cielo",
        "bebe",
        "bebé",
        "corazon",
        "corazón",
        "hermosa",
        "hermoso",
        "linda",
        "lindo",
        "bonita",
        "bonito",
        "guapa",
        "guapo",
        "reina",
        "rey",
        "vida",
        "mi",
    }
)


def _kw_hit(kw: str, lower_text: str) -> bool:
    """Match keyword as a whole-token sequence on lowercased text.

    Single tokens and multi-word phrases both require non-word boundaries on
    both sides so ``eres real`` does not hit ``eres realmente`` / ``realista``.
    """
    k = (kw or "").strip().lower()
    if not k:
        return False
    return re.search(rf"(?<!\w){re.escape(k)}(?!\w)", lower_text) is not None


def _longest_greeting_keyword(lower_text: str) -> str | None:
    """Return the longest PURE_GREETING_PATTERNS hit, or None."""
    hits = [kw for kw in PURE_GREETING_PATTERNS if _kw_hit(kw, lower_text)]
    if not hits:
        return None
    return max(hits, key=len)


def looks_like_pure_greeting_text(text: str) -> bool:
    """True when inbound text is a pure short greeting.

    Contract: known greeting keyword, ≤4 words, and after removing that
    keyword the only leftover tokens are optional vocatives (amor/cielo/…).
    Check-ins like ``Que tal como estas?`` / ``Que tal tu día`` keep the
    keyword + word-count shape but must NOT take the canned saludo pool.
    """
    if not text or not str(text).strip():
        return False
    words = str(text).strip().split()
    if len(words) > PURE_GREETING_MAX_WORDS:
        return False
    lower = str(text).lower()
    matched = _longest_greeting_keyword(lower)
    if matched is None:
        return False
    residual = re.sub(
        rf"(?<!\w){re.escape(matched)}(?!\w)",
        " ",
        lower,
        count=1,
    )
    # Drop punctuation / emoji; keep letters (incl. Spanish accents).
    residual = re.sub(r"[^\w\sáéíóúüñ]", " ", residual, flags=re.UNICODE)
    residual_words = [w for w in residual.split() if w]
    return all(w in _PURE_GREETING_EXTRA_TOKENS for w in residual_words)


class TemplateGate:
    """Match inbound VIP text to the first applicable rule; render a pool response."""

    def __init__(self, rules: list[TemplateRule], *, rng: Any = random) -> None:
        self._rules = list(rules)
        self._rng = rng

    def match(self, text: str) -> TemplateRule | None:
        if not text or not str(text).strip():
            return None
        lower = text.lower()
        words = text.strip().split()
        for rule in self._rules:
            if rule.max_words is not None and len(words) > rule.max_words:
                continue
            if any(_kw_hit(kw, lower) for kw in rule.trigger_patterns):
                return rule
        return None

    def render(self, rule: TemplateRule) -> str:
        if not rule.response_pool:
            raise ValueError(f"TemplateRule {rule.id!r} has empty response_pool")
        if len(rule.response_pool) == 1:
            return rule.response_pool[0]
        return self._rng.choice(rule.response_pool)


__all__ = [
    "PURE_GREETING_MAX_WORDS",
    "PURE_GREETING_PATTERNS",
    "TemplateRule",
    "TemplateGate",
    "looks_like_pure_greeting_text",
]
