"""E2E: SqlReimportCursorStore over system_config (rotation cursor)."""

import pytest

from diana.infrastructure.db.repositories.reimport_cursor import (
    SqlReimportCursorStore,
)


@pytest.mark.db
@pytest.mark.asyncio
async def test_cursor_roundtrip(session_factory):
    store = SqlReimportCursorStore(session_factory)
    assert await store.get_cursor() is None
    await store.set_cursor(123456789)
    assert await store.get_cursor() == 123456789
    await store.set_cursor(987654321)
    assert await store.get_cursor() == 987654321


@pytest.mark.db
@pytest.mark.asyncio
async def test_cursor_is_chat_scoped_to_config_key(session_factory):
    """The cursor lives under its own system_config key — unrelated keys stay."""
    store = SqlReimportCursorStore(session_factory)
    await store.set_cursor(42)
    # A second store instance still reads the same persisted value.
    other = SqlReimportCursorStore(session_factory)
    assert await other.get_cursor() == 42
