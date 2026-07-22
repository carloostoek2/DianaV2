"""BusinessConnectionMiddleware injects BC into data."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from diana.telegram.middlewares.business_connection import BusinessConnectionMiddleware


@pytest.mark.asyncio
async def test_injects_business_connection_id() -> None:
    mw = BusinessConnectionMiddleware()
    event = SimpleNamespace(business_connection_id="bc-xyz")
    data: dict = {}
    handler = AsyncMock(return_value="ok")
    result = await mw(handler, event, data)  # type: ignore[arg-type]
    assert result == "ok"
    assert data["business_connection_id"] == "bc-xyz"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_bc_does_not_inject() -> None:
    mw = BusinessConnectionMiddleware()
    event = SimpleNamespace(business_connection_id=None)
    data: dict = {}
    handler = AsyncMock(return_value=None)
    await mw(handler, event, data)  # type: ignore[arg-type]
    assert "business_connection_id" not in data
