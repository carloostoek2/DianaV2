"""In-memory repository doubles: create/get/transition/cancel semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.memory import (
    InMemoryEscalationStore,
    InMemoryMessageHistoryWriter,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
)
from diana.application.ports import (
    ApprovalRecord,
    DeliveryRecord,
    TurnRecord,
)
from diana.cognitive.models import TERMINAL_TURN_STATUSES, TurnStatus


@pytest.mark.asyncio
async def test_turn_store_create_get_list_non_terminal() -> None:
    store = InMemoryTurnStore()
    t1 = TurnRecord(id=uuid4(), chat_id=1, status=TurnStatus.RECEIVED.value)
    t2 = TurnRecord(id=uuid4(), chat_id=1, status=TurnStatus.PENDING_APPROVAL.value)
    await store.create(t1)
    await store.create(t2)

    assert (await store.get(t1.id)).status == "received"
    non_term = await store.list_non_terminal(1)
    assert {r.id for r in non_term} == {t1.id, t2.id}


@pytest.mark.asyncio
async def test_turn_store_transition_and_supersede_meta() -> None:
    store = InMemoryTurnStore()
    old_id = uuid4()
    new_id = uuid4()
    await store.create(TurnRecord(id=old_id, chat_id=7, status="pending_approval"))
    updated = await store.transition(
        old_id, TurnStatus.SUPERSEDED.value, superseded_by=new_id
    )
    assert updated.status == "superseded"
    assert updated.superseded_by == new_id
    assert old_id not in {r.id for r in await store.list_non_terminal(7)}


@pytest.mark.asyncio
async def test_approval_store_waiting_cancel_for_chat() -> None:
    store = InMemoryPendingApprovalStore()
    a_id = uuid4()
    b_id = uuid4()
    await store.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=a_id,
            chat_id=1,
            business_connection_id="bc",
            draft_text="draft-a",
            status="waiting",
        )
    )
    await store.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=b_id,
            chat_id=2,
            business_connection_id="bc",
            draft_text="draft-b",
            status="waiting",
        )
    )
    n = await store.cancel_waiting_for_chat(1)
    assert n == 1
    a = await store.get_by_turn(a_id)
    b = await store.get_by_turn(b_id)
    assert a is not None and a.status == "cancelled"
    assert b is not None and b.status == "waiting"


@pytest.mark.asyncio
async def test_delivery_store_insert_cancel_list() -> None:
    store = InMemoryPendingDeliveryStore()
    turn_id = uuid4()
    rec = DeliveryRecord(
        id=uuid4(),
        chat_id=9,
        business_connection_id="bc",
        texts=["hola"],
        decision={},
        scheduled_at=datetime.now(UTC),
        status="pending",
        turn_id=turn_id,
    )
    await store.insert_pending(rec)
    assert len(await store.list_pending()) == 1
    n = await store.cancel_for_chat(9)
    assert n == 1
    await store.update_status(rec.id, "cancelled")
    assert (await store.list_pending()) == []


@pytest.mark.asyncio
async def test_escalation_and_history_and_trace_writer() -> None:
    esc = InMemoryEscalationStore()
    hist = InMemoryMessageHistoryWriter()
    traces = InMemoryTraceReaderWriter()
    tid = uuid4()

    await esc.create(tid, tipo="semantica", motivo="risk")
    await esc.mark_notified(tid)
    assert esc.events[0]["notificado"] is True

    await hist.append(42, role="vip", text="hi", telegram_message_id=1)
    recent = await hist.get_recent(42, limit=5)
    assert recent[0]["role"] == "vip"
    assert recent[0]["text"] == "hi"

    await traces.store(tid, "comprehension", {"intent": "x"})
    await traces.set_delivery_result(tid, {"success": True})
    keys = await traces.get_trace_keys(tid)
    assert "comprehension" in keys
    assert traces.get_delivery_result(tid) == {"success": True}


@pytest.mark.asyncio
async def test_terminal_statuses_match_domain() -> None:
    """Non-terminal listing uses the same terminal set as cognitive models."""
    store = InMemoryTurnStore()
    for status in TERMINAL_TURN_STATUSES:
        await store.create(
            TurnRecord(id=uuid4(), chat_id=1, status=status.value)
        )
    await store.create(TurnRecord(id=uuid4(), chat_id=1, status="analyzing"))
    non_term = await store.list_non_terminal(1)
    assert len(non_term) == 1
    assert non_term[0].status == "analyzing"
