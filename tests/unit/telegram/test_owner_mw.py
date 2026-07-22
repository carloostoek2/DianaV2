"""OwnerDetectionMiddleware — cancel_pending; no orchestrator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from diana.telegram.middlewares.owner import OwnerDetectionMiddleware

OWNER = 999001


class _Canceller:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None:
        self.calls.append((chat_id, reason))


@pytest.mark.asyncio
async def test_owner_business_message_cancels_and_stops() -> None:
    behavior = _Canceller()
    mw = OwnerDetectionMiddleware(owner_telegram_id=OWNER, behavior=behavior)
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=OWNER),
        business_connection_id="bc-1",
        chat=SimpleNamespace(id=42),
    )
    data: dict = {"business_connection_id": "bc-1"}
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(handler, event, data)  # type: ignore[arg-type]
    assert result is None
    handler.assert_not_awaited()
    assert behavior.calls == [(42, "owner_message")]


@pytest.mark.asyncio
async def test_non_owner_passes_through() -> None:
    behavior = _Canceller()
    mw = OwnerDetectionMiddleware(owner_telegram_id=OWNER, behavior=behavior)
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=111),
        business_connection_id="bc-1",
        chat=SimpleNamespace(id=42),
    )
    data: dict = {}
    handler = AsyncMock(return_value="next")
    result = await mw(handler, event, data)  # type: ignore[arg-type]
    assert result == "next"
    handler.assert_awaited_once()
    assert behavior.calls == []


@pytest.mark.asyncio
async def test_owner_private_message_continues() -> None:
    behavior = _Canceller()
    mw = OwnerDetectionMiddleware(owner_telegram_id=OWNER, behavior=behavior)
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=OWNER),
        business_connection_id=None,
        chat=SimpleNamespace(id=OWNER),
    )
    data: dict = {}
    handler = AsyncMock(return_value="admin")
    result = await mw(handler, event, data)  # type: ignore[arg-type]
    assert result == "admin"
    assert data.get("is_owner") is True
    assert behavior.calls == []
