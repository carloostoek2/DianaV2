"""CAS claim_waiting semantics — InMemory gold + SQL helper intent."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from diana.application.memory import InMemoryPendingApprovalStore
from diana.application.ports import ApprovalRecord
from diana.infrastructure.db.repositories.turns import apply_terminal_latch


def _approval(turn_id=None, status: str = "waiting") -> ApprovalRecord:
    tid = turn_id or uuid4()
    return ApprovalRecord(
        id=uuid4(),
        turn_id=tid,
        chat_id=42,
        business_connection_id="bc",
        draft_text="draft",
        status=status,
    )


@pytest.mark.asyncio
async def test_claim_waiting_first_wins_inmemory() -> None:
    store = InMemoryPendingApprovalStore()
    rec = _approval()
    await store.create_waiting(rec)
    a = await store.claim_waiting(rec.turn_id)
    b = await store.claim_waiting(rec.turn_id)
    assert a is not None and a.status == "claimed"
    assert b is None
    stored = await store.get_by_turn(rec.turn_id)
    assert stored is not None and stored.status == "claimed"


@pytest.mark.asyncio
async def test_claim_waiting_concurrent_single_winner() -> None:
    store = InMemoryPendingApprovalStore()
    rec = _approval()
    await store.create_waiting(rec)

    results = await asyncio.gather(
        store.claim_waiting(rec.turn_id),
        store.claim_waiting(rec.turn_id),
        store.claim_waiting(rec.turn_id),
    )
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert winners[0].status == "claimed"


@pytest.mark.asyncio
async def test_claim_non_waiting_returns_none() -> None:
    store = InMemoryPendingApprovalStore()
    rec = _approval()
    await store.create_waiting(rec)
    await store.mark_status(rec.turn_id, "cancelled")
    assert await store.claim_waiting(rec.turn_id) is None


def test_terminal_latch_blocks_delivered_to_analyzing() -> None:
    changed, effective = apply_terminal_latch("delivered", "analyzing")
    assert changed is False
    assert effective == "delivered"


def test_terminal_latch_allows_same_terminal() -> None:
    changed, effective = apply_terminal_latch("escalated", "escalated")
    assert changed is True
    assert effective == "escalated"


def test_terminal_latch_allows_live_transition() -> None:
    changed, effective = apply_terminal_latch("received", "analyzing")
    assert changed is True
    assert effective == "analyzing"
