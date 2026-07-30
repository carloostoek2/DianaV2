"""InMemoryBusinessConnectionStore — upsert create + update + deep copy."""

from __future__ import annotations

from datetime import datetime

from diana.application.memory import InMemoryBusinessConnectionStore
from diana.application.ports import BusinessConnectionRecord


def _make_record(
    bc_id: str = "bc-1",
    user_id: int = 111,
    is_enabled: bool = True,
) -> BusinessConnectionRecord:
    return BusinessConnectionRecord(
        business_connection_id=bc_id,
        user_id=user_id,
        user_chat_id=42,
        date=datetime(2026, 7, 30),
        can_reply=True,
        is_enabled=is_enabled,
    )


async def test_upsert_creates_new_record() -> None:
    store = InMemoryBusinessConnectionStore()
    record = _make_record()
    result = await store.upsert(record)
    assert result.business_connection_id == "bc-1"
    assert result.user_id == 111
    assert result.is_enabled is True
    # Internal dict has a deep copy
    assert len(store._connections) == 1


async def test_upsert_updates_existing_record() -> None:
    store = InMemoryBusinessConnectionStore()
    rec1 = _make_record(bc_id="bc-1", is_enabled=True)
    await store.upsert(rec1)
    rec2 = _make_record(bc_id="bc-1", is_enabled=False)
    result = await store.upsert(rec2)
    assert result.is_enabled is False
    assert len(store._connections) == 1


async def test_upsert_returns_deep_copy() -> None:
    store = InMemoryBusinessConnectionStore()
    original = _make_record()
    await store.upsert(original)
    result = await store.upsert(original)
    # Mutating the returned record must not affect the store
    result.is_enabled = False
    stored = store._connections["bc-1"]
    assert stored.is_enabled is True
