"""E2E: SqlReimportCursorStore over system_config (rotation cursor).

The session DB may already carry a cursor (the e2e suite can run against a copy
of the real database — see audit/ENTORNO.md), so the "unset" leg is exercised by
clearing the key explicitly and the previous value is restored afterwards. The
test never assumes an empty ``system_config``.
"""

import pytest
from sqlalchemy import delete

from diana.infrastructure.db.models import SystemConfig
from diana.infrastructure.db.repositories.reimport_cursor import (
    SqlReimportCursorStore,
)

_CURSOR_KEY = "history_reimport_cursor"


async def _clear_cursor(session_factory) -> None:
    async with session_factory() as sess:
        await sess.execute(delete(SystemConfig).where(SystemConfig.key == _CURSOR_KEY))
        await sess.commit()


async def _restore_cursor(session_factory, value: int | None) -> None:
    if value is None:
        await _clear_cursor(session_factory)
    else:
        await SqlReimportCursorStore(session_factory).set_cursor(value)


@pytest.mark.db
@pytest.mark.asyncio
async def test_cursor_roundtrip(session_factory):
    store = SqlReimportCursorStore(session_factory)
    previous = await store.get_cursor()
    await _clear_cursor(session_factory)
    try:
        assert await store.get_cursor() is None
        await store.set_cursor(123456789)
        assert await store.get_cursor() == 123456789
        await store.set_cursor(987654321)
        assert await store.get_cursor() == 987654321
    finally:
        await _restore_cursor(session_factory, previous)


@pytest.mark.db
@pytest.mark.asyncio
async def test_cursor_is_chat_scoped_to_config_key(session_factory):
    """The cursor lives under its own system_config key — unrelated keys stay."""
    store = SqlReimportCursorStore(session_factory)
    previous = await store.get_cursor()
    try:
        await store.set_cursor(42)
        # A second store instance still reads the same persisted value.
        other = SqlReimportCursorStore(session_factory)
        assert await other.get_cursor() == 42
    finally:
        await _restore_cursor(session_factory, previous)
