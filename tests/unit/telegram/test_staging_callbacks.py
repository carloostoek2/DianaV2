"""Staging promote/discard pure dispatch (owner-only, no Telegram network)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.staging_service import AtencionPromoteBlocked
from diana.telegram.handlers.staging import (
    build_staging_router,
    dispatch_staging_callback,
)
from diana.telegram.keyboards import (
    encode_staging_discard,
    encode_staging_discard_cancel,
    encode_staging_discard_confirm,
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
async def test_owner_discard_arms_confirm_prompt(staging: AsyncMock) -> None:
    """A4: the first discard tap only arms the two-step confirm — no delete."""
    cid = uuid4()
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_discard(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "discard_confirm_prompt"
    staging.discard.assert_not_awaited()
    staging.promote_to_example.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_discard_confirm_deletes(staging: AsyncMock) -> None:
    cid = uuid4()
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_discard_confirm(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "discarded"
    staging.discard.assert_awaited_once_with(cid)
    staging.promote_to_example.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_discard_cancel_keeps_candidate(staging: AsyncMock) -> None:
    cid = uuid4()
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_discard_cancel(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "discard_cancelled"
    staging.discard.assert_not_awaited()
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
async def test_promote_atencion_blocked_distinct_status(staging: AsyncMock) -> None:
    """F14: atencion block returns its own token, not the generic 'stale'."""
    cid = uuid4()
    staging.promote_to_example.side_effect = AtencionPromoteBlocked(
        "atencion candidates cannot be promoted to the VIP example bank"
    )
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_promote(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "atencion_blocked"


@pytest.mark.asyncio
async def test_discard_confirm_value_error_stale(staging: AsyncMock) -> None:
    cid = uuid4()
    staging.discard.side_effect = ValueError("not found")
    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_discard_confirm(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "stale"


def test_build_staging_router_when_none() -> None:
    """Router must build without raising when staging is unavailable."""
    router = build_staging_router(staging=None, owner_telegram_id=OWNER)
    assert router is not None
    assert router.name == "staging"


# --- Gray-zone policy promotion (type-routed) --------------------------------


@pytest.mark.asyncio
async def test_policy_promote_routes_to_promote_to_policy() -> None:
    from types import SimpleNamespace
    from uuid import uuid4 as _uuid4

    cid = _uuid4()
    vip_id = _uuid4()
    candidate = SimpleNamespace(
        id=cid,
        candidate_type="policy",
        payload={
            "question": "¿Qué hago si pide descuento?",
            "draft": "borrador",
            "generalization": "Siempre ofrecer 10% si piden 3 o más",
            "rule": "Siempre ofrecer 10% si piden 3 o más",
            "scope": "vip",
            "vip_id": str(vip_id),
        },
    )
    staging = AsyncMock()
    staging.get_candidate = AsyncMock(return_value=candidate)
    staging.promote_to_policy = AsyncMock()
    staging.promote_to_example = AsyncMock()

    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_promote(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "promoted"
    staging.promote_to_example.assert_not_awaited()
    staging.promote_to_policy.assert_awaited_once_with(
        cid,
        trigger="¿Qué hago si pide descuento?",
        rule="Siempre ofrecer 10% si piden 3 o más",
        scope="vip",
        vip_id=vip_id,
    )


@pytest.mark.asyncio
async def test_example_promote_still_uses_promote_to_example() -> None:
    from types import SimpleNamespace
    from uuid import uuid4 as _uuid4

    cid = _uuid4()
    staging = AsyncMock()
    staging.get_candidate = AsyncMock(
        return_value=SimpleNamespace(id=cid, candidate_type="example", payload={})
    )
    staging.promote_to_example = AsyncMock()

    token = await dispatch_staging_callback(
        staging=staging,
        callback_data=encode_staging_promote(cid),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert token == "promoted"
    staging.promote_to_example.assert_awaited_once_with(cid)
