"""Pure repetition detector for consecutive same intents (H4).

No I/O. Counts current intent plus consecutive equals in recent (DESC, newest
first). Blank current intent never escalates.
"""

from __future__ import annotations


class RepetitionGuard:
    """Return True when same intent streak reaches ``threshold`` (default 3)."""

    def __init__(self, threshold: int = 3) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        self._threshold = threshold

    @property
    def threshold(self) -> int:
        return self._threshold

    def is_repeated(self, current_intent: str, recent_intents: list[str]) -> bool:
        if not current_intent or not current_intent.strip():
            return False
        # Normalize intent for case/whitespace resilience (ROADMAP 5.1):
        # the Analyst emits free lowercase verb_object labels today; if a
        # future Analyst change introduces case variation, the streak must
        # still match ("Saludar" and "saludar " should count as the same).
        canonical = current_intent.strip().lower()
        streak = 1
        for intent in recent_intents:
            if not intent:
                continue
            if intent.strip().lower() == canonical:
                streak += 1
            else:
                break
        return streak >= self._threshold


__all__ = ["RepetitionGuard"]
