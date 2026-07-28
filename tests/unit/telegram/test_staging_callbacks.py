"""Staging promote/discard pure dispatch (owner-only, no Telegram network)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.telegram.handlers.staging import (
    build_staging_router,
    dispatch_staging_callback,
)
from diana.telegram.keyboards import (
    encode_staging_discard,
    encode_staging_promote,
)

OWNER = 999001
OTHER = 111222


@pytest.fixture
def staging() -> AsyncMock:
    svc = AsyncMock()
    svc.promote_to_example = AsyncMock()
    svc.discard = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_owner_promote_success(staging: AsyncMock) -> None:
    cid = uuid4()
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_promote(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "promoted"
    staging.promote_to_example.assert_awaited_once_with(cid)
    staging.discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_discard_success(staging: AsyncMock) -> None:
    cid = uuid4()
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_discard(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "discarded"
    staging.discard.assert_awaited_once_with(cid)
    staging.promote_to_example.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_owner_forbidden(staging: AsyncMock) -> None:
    cid = uuid4()
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_promote(cid),
        actor_id=OTHER,
        owner_telegram_id=OWNER,
    )
    assert token == "forbidden"
    staging.promote_to_example.assert_not_awaited()
    staging.discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_staging_none_unavailable() -> None:
    token = await dispatch_staging_callback(
        staging=None,
        callback_data=encode_staging_promote(uuid4()),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "unavailable"


@pytest.mark.asyncio
async def test_invalid_callback_data(staging: AsyncMock) -> None:
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data="mx:e",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "invalid"
    staging.promote_to_example.assert_not_awaited()


@pytest.mark.asyncio
async def test_promote_value_error_stale(staging: AsyncMock) -> None:
    cid = uuid4()
    staging.promote_to_example.side_effect = ValueError("not pending")
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_promote(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "stale"


@pytest.mark.asyncio
async def test_discard_value_error_stale(staging: AsyncMock) -> None:
    cid = uuid4()
    staging.discard.side_effect = ValueError("not found")
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_discard(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "stale"


def test_build_staging_router_when_none() -> None:
    """Router must build without raising when staging is unavailable."""
    router = build_staging_router(staging=None, owner_telegram_id=OWNER)
    assert router is not None
    assert router.name == "staging"
