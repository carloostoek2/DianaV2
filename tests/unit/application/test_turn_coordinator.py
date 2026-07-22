"""TurnCoordinator: one non-terminal turn per chat + supersede cascade."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from diana.application.memory import (
    InMemoryPendingApprovalStore,
    InMemoryTurnStore,
)
from diana.application.ports import ApprovalRecord, TurnRecord
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.models import TurnStatus


class FakeCanceller:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None:
        self.calls.append((chat_id, reason))


@pytest.fixture
def coordinator() -> tuple[TurnCoordinator, InMemoryTurnStore, InMemoryPendingApprovalStore, FakeCanceller]:
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    canceller = FakeCanceller()
    coord = TurnCoordinator(turns, approvals, canceller)
    return coord, turns, approvals, canceller


@pytest.mark.asyncio
async def test_first_begin_turn_received_single_non_terminal(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    rec = await coord.begin_turn(chat_id=100, trigger_message_id=1)
    assert rec.status == TurnStatus.RECEIVED.value
    assert rec.chat_id == 100
    non_term = await turns.list_non_terminal(100)
    assert len(non_term) == 1
    assert non_term[0].id == rec.id


@pytest.mark.asyncio
async def test_second_begin_turn_supersedes_previous(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    first = await coord.begin_turn(chat_id=100)
    second = await coord.begin_turn(chat_id=100)
    assert second.id != first.id
    old = await turns.get(first.id)
    assert old is not None
    assert old.status == TurnStatus.SUPERSEDED.value
    assert old.superseded_by == second.id
    assert second.status == TurnStatus.RECEIVED.value
    non_term = await turns.list_non_terminal(100)
    assert len(non_term) == 1
    assert non_term[0].id == second.id


@pytest.mark.asyncio
async def test_supersede_calls_cancel_pending_once(
    coordinator: tuple,
) -> None:
    coord, _, _, canceller = coordinator
    await coord.begin_turn(chat_id=5)
    await coord.begin_turn(chat_id=5)
    assert canceller.calls == [(5, "new_message")]


@pytest.mark.asyncio
async def test_supersede_cancels_waiting_approvals(
    coordinator: tuple,
) -> None:
    coord, _, approvals, _ = coordinator
    first = await coord.begin_turn(chat_id=8)
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=first.id,
            chat_id=8,
            business_connection_id="bc",
            draft_text="draft",
            status="waiting",
        )
    )
    await coord.begin_turn(chat_id=8)
    appr = await approvals.get_by_turn(first.id)
    assert appr is not None
    assert appr.status == "cancelled"


@pytest.mark.asyncio
async def test_concurrent_begin_turn_one_non_terminal(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    results = await asyncio.gather(
        coord.begin_turn(chat_id=77),
        coord.begin_turn(chat_id=77),
        coord.begin_turn(chat_id=77),
    )
    assert len({r.id for r in results}) == 3
    non_term = await turns.list_non_terminal(77)
    assert len(non_term) == 1


@pytest.mark.asyncio
async def test_transition_terminal_and_pending(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    rec = await coord.begin_turn(chat_id=1)
    await coord.transition(rec.id, TurnStatus.PENDING_APPROVAL)
    assert (await turns.get(rec.id)).status == "pending_approval"
    await coord.transition(rec.id, TurnStatus.DELIVERED)
    assert (await turns.get(rec.id)).status == "delivered"
    rec2 = await coord.begin_turn(chat_id=2)
    await coord.transition(rec2.id, "escalated")
    assert (await turns.get(rec2.id)).status == "escalated"
    rec3 = await coord.begin_turn(chat_id=3)
    await coord.mark_failed(rec3.id, error="boom")
    failed = await turns.get(rec3.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == "boom"


@pytest.mark.asyncio
async def test_transition_sink_for_director(
    coordinator: tuple,
) -> None:
    coord, turns, _, _ = coordinator
    rec = await coord.begin_turn(chat_id=1)
    await coord.transition_sink(rec.id, TurnStatus.ANALYZING)
    assert (await turns.get(rec.id)).status == "analyzing"


@pytest.mark.asyncio
async def test_begin_turn_accepts_explicit_turn_id(
    coordinator: tuple,
) -> None:
    coord, _, _, _ = coordinator
    tid = uuid4()
    rec = await coord.begin_turn(chat_id=1, turn_id=tid, vip_id=uuid4())
    assert rec.id == tid
    assert isinstance(rec.id, UUID)
    assert rec.vip_id is not None
