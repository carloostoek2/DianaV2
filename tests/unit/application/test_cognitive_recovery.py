"""Tests for cognitive_recovery — zombie turns + draft re-materialization."""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.application.cognitive_recovery import (
    recover_zombie_turns,
    rematerialize_drafts,
)
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryPendingApprovalStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
)
from diana.application.ports import TurnRecord


@pytest.mark.asyncio
async def test_recover_zombie_turns_marks_non_terminal_as_failed() -> None:
    """recover_zombie_turns marks all non-terminal turns as FAILED with error='crash_recovery'."""
    turns = InMemoryTurnStore()
    t1 = TurnRecord(id=uuid4(), chat_id=1, status="analyzing")
    t2 = TurnRecord(id=uuid4(), chat_id=2, status="generating")
    t3 = TurnRecord(id=uuid4(), chat_id=1, status="deciding")
    t4 = TurnRecord(id=uuid4(), chat_id=2, status="failed")  # already terminal
    await turns.create(t1)
    await turns.create(t2)
    await turns.create(t3)
    await turns.create(t4)

    count = await recover_zombie_turns(turns)
    assert count == 3  # t1, t2, t3 marked; t4 skipped (terminal latch)

    for turn_id in (t1.id, t2.id, t3.id):
        rec = await turns.get(turn_id)
        assert rec is not None
        assert rec.status == "failed"
        assert rec.error == "crash_recovery"

    # Terminal turn unchanged (terminal latch prevents re-transition)
    rec4 = await turns.get(t4.id)
    assert rec4 is not None
    assert rec4.status == "failed"
    # error is None because the original TurnRecord was created without error,
    # and the terminal latch skips the transition entirely
    assert rec4.error is None


@pytest.mark.asyncio
async def test_rematerialize_drafts_creates_approval_and_notifies() -> None:
    """rematerialize_drafts creates pending approval records and notifies owner."""
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    t1 = TurnRecord(id=uuid4(), chat_id=1, status="generating")
    t2 = TurnRecord(id=uuid4(), chat_id=2, status="deciding")

    rematerializable = [(t1, "generated text 1"), (t2, "generated text 2")]
    count = await rematerialize_drafts(rematerializable, approvals, notifier)
    assert count == 2

    assert len(notifier.drafts) == 2
    for notif in notifier.drafts:
        assert notif.reason == "crash_rematerialized"
        assert notif.business_connection_id == ""

    for turn, text in rematerializable:
        stored = await approvals.get_by_turn(turn.id)
        assert stored is not None
        assert stored.draft_text == text
        assert stored.status == "waiting"
        assert stored.business_connection_id == ""


@pytest.mark.asyncio
async def test_rematerialize_drafts_empty_noop() -> None:
    """Empty rematerializable list is a no-op."""
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    count = await rematerialize_drafts([], approvals, notifier)
    assert count == 0
    assert len(notifier.drafts) == 0
    assert len(await approvals.list_waiting()) == 0


@pytest.mark.asyncio
async def test_list_zombie_turns_returns_all_non_terminal() -> None:
    """list_zombie_turns returns non-terminal turns only."""
    from diana.application.recovery import list_zombie_turns

    turns = InMemoryTurnStore()
    t1 = TurnRecord(id=uuid4(), chat_id=1, status="analyzing")
    t2 = TurnRecord(id=uuid4(), chat_id=1, status="delivered")  # terminal
    t3 = TurnRecord(id=uuid4(), chat_id=2, status="pending_approval")  # non-terminal
    await turns.create(t1)
    await turns.create(t2)
    await turns.create(t3)

    zombies = await list_zombie_turns(turns)
    ids = {z.id for z in zombies}
    assert t1.id in ids
    assert t2.id not in ids
    assert t3.id in ids


@pytest.mark.asyncio
async def test_list_rematerializable_turns_filters_by_status_and_trace() -> None:
    """list_rematerializable_turns returns (turn, text) for turns with generated_text."""
    from diana.application.recovery import list_rematerializable_turns

    turns = InMemoryTurnStore()
    traces = InMemoryTraceReaderWriter()

    t1 = TurnRecord(id=uuid4(), chat_id=1, status="generating")
    t2 = TurnRecord(id=uuid4(), chat_id=2, status="deciding")
    t3 = TurnRecord(id=uuid4(), chat_id=1, status="analyzing")  # not in {generating, evaluating, deciding}
    t4 = TurnRecord(id=uuid4(), chat_id=2, status="generating")  # no trace stored
    await turns.create(t1)
    await turns.create(t2)
    await turns.create(t3)
    await turns.create(t4)

    await traces.store(t1.id, "generated_text", "hello world")
    await traces.store(t2.id, "generated_text", "another draft")

    result = await list_rematerializable_turns(turns, traces)
    result_map = {r[0].id: r[1] for r in result}
    assert t1.id in result_map
    assert result_map[t1.id] == "hello world"
    assert t2.id in result_map
    assert result_map[t2.id] == "another draft"
    assert t3.id not in result_map
    assert t4.id not in result_map
