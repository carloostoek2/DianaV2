"""OwnerDetectionMiddleware — coordinator discard on business; no orchestrator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

from diana.application.memory import (
    InMemoryMessageHistoryWriter,
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


# --- What the owner sends is recorded with a media tag -----------------------
#
# Before this, her media was stored as an empty string, so the model read a
# blank "dueña" line and could not tell an image from a video. The tag now
# comes from the same helper as the VIP path, album mark included.

def _owner_photo(*, media_group_id: str | None = None, caption: str | None = None) -> Message:
    """A photo sent by the owner in the VIP chat (real aiogram payload)."""
    return Message(
        message_id=55,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        media_group_id=media_group_id,
        photo=[PhotoSize(file_id="p1", file_unique_id="u1", width=9, height=9)],
        caption=caption,
        business_connection_id="bc-1",
    )


def _owner_text() -> Message:
    return Message(
        message_id=56,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="ya te atiendo yo",
        business_connection_id="bc-1",
    )


async def _recorded_text(event: object) -> str:
    coord, _, _, _ = _make_coordinator()
    hist = InMemoryMessageHistoryWriter()
    mw = OwnerDetectionMiddleware(
        owner_telegram_id=OWNER, coordinator=coord, history=hist
    )
    await mw(AsyncMock(), event, {"business_connection_id": "bc-1"})  # type: ignore[arg-type]
    rows = await hist.get_recent(42)
    assert len(rows) == 1
    assert rows[0]["role"] == "owner"
    return str(rows[0]["text"])


@pytest.mark.asyncio
async def test_owner_photo_recorded_with_tag_not_blank() -> None:
    assert await _recorded_text(_owner_photo()) == "[imagen]"


@pytest.mark.asyncio
async def test_owner_photo_keeps_caption_after_tag() -> None:
    assert await _recorded_text(_owner_photo(caption="mira")) == "[imagen] mira"


@pytest.mark.asyncio
async def test_owner_album_photo_marked_as_part_of_album() -> None:
    assert (
        await _recorded_text(_owner_photo(media_group_id="grp-9"))
        == "[imagen parte de álbum]"
    )


@pytest.mark.asyncio
async def test_owner_text_message_unchanged() -> None:
    """Non-media keeps her words verbatim — the tag must not leak into text."""
    assert await _recorded_text(_owner_text()) == "ya te atiendo yo"
