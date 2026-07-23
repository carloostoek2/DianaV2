"""OwnerDetectionMiddleware — coordinator discard on business; no orchestrator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.memory import (
    InMemoryPendingApprovalStore,
    InMemoryTurnStore,
)
from diana.application.ports import ApprovalRecord
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.models import TurnStatus
from diana.telegram.middlewares.owner import OwnerDetectionMiddleware

OWNER = 999001


class FakeCanceller:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None:
        self.calls.append((chat_id, reason))


def _make_coordinator() -> tuple[
    TurnCoordinator, InMemoryTurnStore, InMemoryPendingApprovalStore, FakeCanceller
]:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    canceller = FakeCanceller()
    coord = TurnCoordinator(turns, approvals, canceller)
    return coord, turns, approvals, canceller


@pytest.mark.asyncio
async def test_owner_business_message_cancels_and_stops() -> None:
    coord, _, _, canceller = _make_coordinator()
    mw = OwnerDetectionMiddleware(owner_telegram_id=OWNER, coordinator=coord)
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=OWNER),
        business_connection_id="bc-1",
        chat=SimpleNamespace(id=42),
        message_id=10,
    )
    data: dict = {"business_connection_id": "bc-1"}
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(handler, event, data)  # type: ignore[arg-type]
    assert result is None
    handler.assert_not_awaited()
    # Idle owner still coordinates discard; cascade cancel is optional no-op.
    assert canceller.calls == [] or canceller.calls == [(42, "owner_message")]


@pytest.mark.asyncio
async def test_non_owner_passes_through() -> None:
    coord, _, _, canceller = _make_coordinator()
    mw = OwnerDetectionMiddleware(owner_telegram_id=OWNER, coordinator=coord)
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
    assert canceller.calls == []


@pytest.mark.asyncio
async def test_owner_private_message_continues() -> None:
    coord, _, _, canceller = _make_coordinator()
    mw = OwnerDetectionMiddleware(owner_telegram_id=OWNER, coordinator=coord)
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
    assert canceller.calls == []


@pytest.mark.asyncio
async def test_owner_mw_business_supersedes_pending_approval() -> None:
    coord, turns, approvals, canceller = _make_coordinator()
    first = await coord.begin_turn(chat_id=42)
    await coord.transition(first.id, TurnStatus.PENDING_APPROVAL)
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=first.id,
            chat_id=42,
            business_connection_id="bc-1",
            draft_text="draft",
            status="waiting",
        )
    )
    mw = OwnerDetectionMiddleware(owner_telegram_id=OWNER, coordinator=coord)
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=OWNER),
        business_connection_id="bc-1",
        chat=SimpleNamespace(id=42),
        message_id=99,
    )
    data: dict = {"business_connection_id": "bc-1"}
    handler = AsyncMock(return_value="should-not-run")
    result = await mw(handler, event, data)  # type: ignore[arg-type]
    assert result is None
    handler.assert_not_awaited()
    assert await turns.list_non_terminal(42) == []
    old = await turns.get(first.id)
    assert old is not None
    assert old.status == TurnStatus.SUPERSEDED.value
    assert old.superseded_by is None
    appr = await approvals.get_by_turn(first.id)
    assert appr is not None
    assert appr.status == "cancelled"
    assert canceller.calls == [(42, "owner_message")]


@pytest.mark.asyncio
async def test_owner_mw_private_does_not_coordinate_discard() -> None:
    """Owner private DM must not supersede a live VIP turn on another chat."""
    coord, turns, _, _ = _make_coordinator()
    vip_chat = 777
    live = await coord.begin_turn(chat_id=vip_chat)
    await coord.transition(live.id, TurnStatus.PENDING_APPROVAL)

    mw = OwnerDetectionMiddleware(owner_telegram_id=OWNER, coordinator=coord)
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=OWNER),
        business_connection_id=None,
        chat=SimpleNamespace(id=OWNER),
    )
    data: dict = {}
    handler = AsyncMock(return_value="admin")
    result = await mw(handler, event, data)  # type: ignore[arg-type]
    assert result == "admin"
    handler.assert_awaited_once()
    non_term = await turns.list_non_terminal(vip_chat)
    assert len(non_term) == 1
    assert non_term[0].id == live.id
    assert non_term[0].status == TurnStatus.PENDING_APPROVAL.value
