"""BusinessConnection lifecycle handler — upsert + logging + error swallow."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import BusinessConnection, User

from diana.application.ports import BusinessConnectionRecord
from diana.telegram.handlers.business_connection import (
    build_business_connection_router,
)


def _biz_connection(is_enabled: bool = True) -> BusinessConnection:
    return BusinessConnection(
        id="bc-1",
        user=User(id=111, is_bot=False, first_name="Test"),
        user_chat_id=42,
        date=datetime(2026, 7, 30, tzinfo=UTC),
        can_reply=True,
        is_enabled=is_enabled,
    )


@pytest.mark.asyncio
async def test_handler_calls_store_upsert() -> None:
    store = AsyncMock()
    store.upsert = AsyncMock(return_value=None)
    router = build_business_connection_router(store=store)
    handler = router.business_connection.handlers[0].callback
    await handler(_biz_connection(is_enabled=True))
    store.upsert.assert_awaited_once()
    args = store.upsert.await_args.args[0]
    assert isinstance(args, BusinessConnectionRecord)
    assert args.business_connection_id == "bc-1"
    assert args.user_id == 111
    assert args.user_chat_id == 42
    assert args.is_enabled is True
    assert args.can_reply is True


@pytest.mark.asyncio
async def test_handler_logs_enabled() -> None:
    store = AsyncMock()
    store.upsert = AsyncMock(return_value=None)
    router = build_business_connection_router(store=store)
    handler = router.business_connection.handlers[0].callback
    with patch("diana.telegram.handlers.business_connection.logger") as mock_logger:
        await handler(_biz_connection(is_enabled=True))
    mock_logger.info.assert_called_once()
    assert mock_logger.info.call_args.args[0] == "business_connection_enabled"
    extra = mock_logger.info.call_args.kwargs.get("extra") or {}
    assert extra.get("business_connection_id") == "bc-1"
    assert extra.get("user_id") == 111


@pytest.mark.asyncio
async def test_handler_logs_disabled() -> None:
    store = AsyncMock()
    store.upsert = AsyncMock(return_value=None)
    router = build_business_connection_router(store=store)
    handler = router.business_connection.handlers[0].callback
    with patch("diana.telegram.handlers.business_connection.logger") as mock_logger:
        await handler(_biz_connection(is_enabled=False))
    mock_logger.info.assert_called_once()
    assert mock_logger.info.call_args.args[0] == "business_connection_disabled"
    extra = mock_logger.info.call_args.kwargs.get("extra") or {}
    assert extra.get("business_connection_id") == "bc-1"


@pytest.mark.asyncio
async def test_handler_swallows_store_exception() -> None:
    store = AsyncMock()
    store.upsert = AsyncMock(side_effect=RuntimeError("db down"))
    router = build_business_connection_router(store=store)
    handler = router.business_connection.handlers[0].callback
    with patch("diana.telegram.handlers.business_connection.logger") as mock_logger:
        # Must not raise — handler swallows exceptions.
        await handler(_biz_connection(is_enabled=True))
    store.upsert.assert_awaited_once()
    mock_logger.exception.assert_called()
    assert mock_logger.exception.call_args.args[0] == "business_connection_handler_error"
    extra = mock_logger.exception.call_args.kwargs["extra"]
    assert extra["business_connection_id"] == "bc-1"
    assert extra["user_id"] == 111
