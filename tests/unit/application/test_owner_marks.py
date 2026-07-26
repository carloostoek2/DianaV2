"""Owner false-positive mark store (R5 residual)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.owner_marks import InMemoryOwnerMarkStore


@pytest.mark.asyncio
async def test_mark_and_count_in_range() -> None:
    store = InMemoryOwnerMarkStore()
    t1 = uuid4()
    t2 = uuid4()
    clock = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
    store._clock = lambda: clock  # noqa: SLF001
    await store.mark(t1)
    await store.mark(t2)
    # idempotent rematch
    await store.mark(t1)
    start = date(2026, 7, 13)
    end = date(2026, 7, 20)
    assert await store.count_in_range(start, end) == 2
    assert await store.count_in_range(date(2026, 6, 1), date(2026, 6, 8)) == 0


@pytest.mark.asyncio
async def test_mark_outside_range_excluded() -> None:
    store = InMemoryOwnerMarkStore()
    old = uuid4()
    store._clock = lambda: datetime(2026, 6, 1, tzinfo=UTC)  # noqa: SLF001
    await store.mark(old)
    store._clock = lambda: datetime(2026, 7, 15, tzinfo=UTC)  # noqa: SLF001
    await store.mark(uuid4())
    assert await store.count_in_range(date(2026, 7, 13), date(2026, 7, 20)) == 1
