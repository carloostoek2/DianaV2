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
        streak = 1
        for intent in recent_intents:
            if intent == current_intent:
                streak += 1
            else:
                break
        return streak >= self._threshold


__all__ = ["RepetitionGuard"]
