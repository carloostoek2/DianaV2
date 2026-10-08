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
    assert result.user_chat_id == 42
    assert result.can_reply is True
    assert result.date == datetime(2026, 7, 30)


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
    result2 = await store.upsert(original)
    assert result2.is_enabled is True


# --- lectura por chat (arranque de un VIP nuevo) -----------------------------


async def test_get_active_returns_the_live_connection() -> None:
    store = InMemoryBusinessConnectionStore()
    await store.upsert(_make_record("bc-1"))
    found = await store.get_active()
    assert found is not None
    assert found.business_connection_id == "bc-1"


async def test_get_active_ignores_a_disabled_connection() -> None:
    store = InMemoryBusinessConnectionStore()
    await store.upsert(_make_record("bc-1", is_enabled=False))
    assert await store.get_active() is None


async def test_get_active_ignores_a_connection_that_cannot_reply() -> None:
    store = InMemoryBusinessConnectionStore()
    record = _make_record("bc-1")
    record.can_reply = False
    await store.upsert(record)
    assert await store.get_active() is None


async def test_get_active_prefers_the_most_recent() -> None:
    store = InMemoryBusinessConnectionStore()
    vieja = _make_record("bc-vieja")
    vieja.date = datetime(2026, 1, 1)
    nueva = _make_record("bc-nueva")
    nueva.date = datetime(2026, 10, 8)
    await store.upsert(vieja)
    await store.upsert(nueva)
    found = await store.get_active()
    assert found is not None
    assert found.business_connection_id == "bc-nueva"


async def test_get_active_is_none_without_any_connection() -> None:
    store = InMemoryBusinessConnectionStore()
    assert await store.get_active() is None


async def test_get_active_is_none_when_nothing_can_reply() -> None:
    store = InMemoryBusinessConnectionStore()
    record = _make_record("bc-1")
    record.can_reply = False
    await store.upsert(record)
    assert await store.get_active() is None
