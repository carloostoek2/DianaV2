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
async def test_recover_zombie_turns_marks_pipeline_only_as_failed() -> None:
    """recover_zombie_turns fails mid-pipeline zombies, keeps pending_approval alive."""
    turns = InMemoryTurnStore()
    t1 = TurnRecord(id=uuid4(), chat_id=1, status="analyzing")
    t2 = TurnRecord(id=uuid4(), chat_id=2, status="generating")
    t3 = TurnRecord(id=uuid4(), chat_id=1, status="deciding")
    t4 = TurnRecord(id=uuid4(), chat_id=2, status="failed")  # already terminal
    t5 = TurnRecord(id=uuid4(), chat_id=3, status="pending_approval")  # owner waiting
    t6 = TurnRecord(id=uuid4(), chat_id=4, status="waiting_delay")  # pre-delay zombie
    await turns.create(t1)
    await turns.create(t2)
    await turns.create(t3)
    await turns.create(t4)
    await turns.create(t5)
    await turns.create(t6)

    count = await recover_zombie_turns(turns)
    assert count == 4  # t1, t2, t3, t6

    for turn_id in (t1.id, t2.id, t3.id, t6.id):
        rec = await turns.get(turn_id)
        assert rec is not None
        assert rec.status == "failed"
        assert rec.error == "crash_recovery"

    rec4 = await turns.get(t4.id)
    assert rec4 is not None
    assert rec4.status == "failed"
    assert rec4.error is None

    rec5 = await turns.get(t5.id)
    assert rec5 is not None
    assert rec5.status == "pending_approval"


@pytest.mark.asyncio
async def test_rematerialize_drafts_creates_approval_and_parks_turn() -> None:
    """rematerialize creates waiting approval and sets turn to pending_approval."""
    approvals = InMemoryPendingApprovalStore()
    notifier = FakeOwnerNotifier()
    turns = InMemoryTurnStore()
    t1 = TurnRecord(id=uuid4(), chat_id=1, status="generating")
    t2 = TurnRecord(id=uuid4(), chat_id=2, status="deciding")
    await turns.create(t1)
    await turns.create(t2)

    rematerializable = [(t1, "generated text 1"), (t2, "generated text 2")]
    count = await rematerialize_drafts(
        rematerializable, approvals, notifier, turns=turns
    )
    assert count == 2
    # Notify is deferred to startup re-notify pass (avoid double DMs).
    assert len(notifier.drafts) == 0

    for turn, text in rematerializable:
        stored = await approvals.get_by_turn(turn.id)
        assert stored is not None
        assert stored.draft_text == text
        assert stored.status == "waiting"
        rec = await turns.get(turn.id)
        assert rec is not None
        assert rec.status == "pending_approval"


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
async def test_list_zombie_turns_excludes_owner_waiting() -> None:
    """list_zombie_turns is mid-pipeline only — not pending_approval / gray_zone."""
    from diana.application.recovery import list_zombie_turns

    turns = InMemoryTurnStore()
    t1 = TurnRecord(id=uuid4(), chat_id=1, status="analyzing")
    t2 = TurnRecord(id=uuid4(), chat_id=1, status="delivered")  # terminal
    t3 = TurnRecord(id=uuid4(), chat_id=2, status="pending_approval")  # owner waiting
    t4 = TurnRecord(id=uuid4(), chat_id=2, status="gray_zone")  # owner waiting
    t5 = TurnRecord(id=uuid4(), chat_id=3, status="waiting_delay")  # pre-delay zombie
    await turns.create(t1)
    await turns.create(t2)
    await turns.create(t3)
    await turns.create(t4)
    await turns.create(t5)

    zombies = await list_zombie_turns(turns)
    ids = {z.id for z in zombies}
    assert t1.id in ids
    assert t5.id in ids
    assert t2.id not in ids
    assert t3.id not in ids
    assert t4.id not in ids


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
