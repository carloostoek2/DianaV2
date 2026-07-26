"""Owner false-positive escalation marks (metrics residual R5).

Thin application port + in-memory double. SQL adapter lives under infrastructure.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

__all__ = [
    "FALSE_POSITIVE_KIND",
    "InMemoryOwnerMarkStore",
    "OwnerMarkStore",
]

FALSE_POSITIVE_KIND = "false_positive"


class OwnerMarkStore(Protocol):
    async def mark(
        self, turn_id: UUID, *, kind: str = FALSE_POSITIVE_KIND
    ) -> None: ...

    async def count_in_range(
        self,
        week_start: date,
        week_end: date,
        *,
        kind: str = FALSE_POSITIVE_KIND,
    ) -> int: ...


class InMemoryOwnerMarkStore:
    """Dict-backed OwnerMarkStore for unit tests."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # turn_id -> (kind, created_at); last mark wins per turn_id+kind
        self._marks: dict[tuple[UUID, str], datetime] = {}
        self._clock = clock or (lambda: datetime.now(UTC))

    async def mark(
        self, turn_id: UUID, *, kind: str = FALSE_POSITIVE_KIND
    ) -> None:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        self._marks[(turn_id, kind)] = now

    async def count_in_range(
        self,
        week_start: date,
        week_end: date,
        *,
        kind: str = FALSE_POSITIVE_KIND,
    ) -> int:
        start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)
        end = datetime(week_end.year, week_end.month, week_end.day, tzinfo=UTC)
        n = 0
        for (tid, k), created in self._marks.items():
            if k != kind:
                continue
            ts = created if created.tzinfo else created.replace(tzinfo=UTC)
            if start <= ts < end:
                n += 1
        return n
