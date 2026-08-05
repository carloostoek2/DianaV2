"""Memory approval pure dispatch (owner-only, no Telegram network)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.telegram.handlers.memory_approval import (
    build_memory_approval_router,
    dispatch_memory_approval_callback,
)
from diana.telegram.keyboards import (
    encode_memory_approve,
    encode_memory_discard,
)

OWNER = 999002
OTHER = 111222


@pytest.fixture
def memory() -> AsyncMock:
    svc = AsyncMock()
    svc.approve = AsyncMock(return_value="approved")
    svc.discard = AsyncMock(return_value="discarded")
    return svc


@pytest.mark.asyncio
async def test_owner_approve_success(memory: AsyncMock) -> None:
    fid = uuid4()
    token = await dispatch_memory_approval_callback(
        memory=memory,
        callback_data=encode_memory_approve(fid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "approved"
    memory.approve.assert_awaited_once_with(OWNER, fid)
    memory.discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_discard_success(memory: AsyncMock) -> None:
    fid = uuid4()
    token = await dispatch_memory_approval_callback(
        memory=memory,
        callback_data=encode_memory_discard(fid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "discarded"
    memory.discard.assert_awaited_once_with(OWNER, fid)
    memory.approve.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_owner_forbidden(memory: AsyncMock) -> None:
    fid = uuid4()
    token = await dispatch_memory_approval_callback(
        memory=memory,
        callback_data=encode_memory_approve(fid),
        actor_id=OTHER,
        owner_telegram_id=OWNER,
    )
    assert token == "forbidden"
    memory.approve.assert_not_awaited()
    memory.discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_none_unavailable() -> None:
    token = await dispatch_memory_approval_callback(
        memory=None,
        callback_data=encode_memory_approve(uuid4()),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "unavailable"


@pytest.mark.asyncio
async def test_invalid_callback_data(memory: AsyncMock) -> None:
    token = await dispatch_memory_approval_callback(
        memory=memory,
        callback_data="mx:e",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "invalid"
    memory.approve.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_token_from_service(memory: AsyncMock) -> None:
    fid = uuid4()
    memory.approve.side_effect = ValueError("not pending")
    token = await dispatch_memory_approval_callback(
        memory=memory,
        callback_data=encode_memory_approve(fid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "stale"


def test_build_router_when_none() -> None:
    """Router must build without raising when memory approval is unavailable."""
    router = build_memory_approval_router(
        memory=None, owner_telegram_id=OWNER
    )
    assert router is not None
    assert router.name == "memory_approval"
