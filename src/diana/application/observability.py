"""Process-local swallowed-exception observability (single-instance).

Call ``log_swallowed`` only from inside an active ``except`` block so
``logger.exception`` captures the active exception context.

Counters are process-local for tests and future ops — not exposed on /health.
"""

from __future__ import annotations

import logging
from collections import Counter

_SWALLOWED: Counter[str] = Counter()


def log_swallowed(logger: logging.Logger, event: str, **extra: object) -> None:
    """Increment counter then log exception for a fail-soft swallow site."""
    _SWALLOWED[event] += 1
    logger.exception(event, extra=extra or None)


def get_swallowed_counts() -> dict[str, int]:
    return dict(_SWALLOWED)


def reset_swallowed_counts() -> None:
    """Test helper — clear process-local counters."""
    _SWALLOWED.clear()


__all__ = [
    "get_swallowed_counts",
    "log_swallowed",
    "reset_swallowed_counts",
]
