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


def _kw_hit(kw: str, lower_text: str) -> bool:
    """Match keyword as a whole-token sequence on lowercased text.

    Single tokens and multi-word phrases both require non-word boundaries on
    both sides so ``eres real`` does not hit ``eres realmente`` / ``realista``.
    """
    k = (kw or "").strip().lower()
    if not k:
        return False
    return re.search(rf"(?<!\w){re.escape(k)}(?!\w)", lower_text) is not None



def looks_like_pure_greeting_text(text: str) -> bool:
    """True when inbound text is a short greeting (keyword + ≤4 words)."""
    if not text or not str(text).strip():
        return False
    words = str(text).strip().split()
    if len(words) > PURE_GREETING_MAX_WORDS:
        return False
    lower = str(text).lower()
    return any(_kw_hit(kw, lower) for kw in PURE_GREETING_PATTERNS)


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
