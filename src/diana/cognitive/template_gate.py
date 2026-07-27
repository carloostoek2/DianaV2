"""Pure deterministic template matcher for short VIP replies (H6).

No I/O, no LLM. Cognitive Core only — does not import application/telegram/behavior.
Keyword hit semantics mirror application.j4_triggers.match_keywords (local copy).
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


def _kw_hit(kw: str, lower_text: str) -> bool:
    """Match keyword as a whole-token sequence on lowercased text.

    Single tokens and multi-word phrases both require non-word boundaries on
    both sides so ``eres real`` does not hit ``eres realmente`` / ``realista``.
    """
    k = (kw or "").strip().lower()
    if not k:
        return False
    return re.search(rf"(?<!\w){re.escape(k)}(?!\w)", lower_text) is not None



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


__all__ = ["TemplateRule", "TemplateGate"]
