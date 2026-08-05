"""E2E: SqlTraceStore channel_type propagation against real PostgreSQL.

Covers the production path ``store()`` → ``_ensure_row``: a new
``pipeline_traces`` row copies ``channel_type`` (and ``chat_id``/``vip_id``)
from the owning Turn. REQ-ATN-13 — atencion turns persist
``channel_type='atencion'``; VIP turns keep the ``'vip'`` default.
"""

from uuid import uuid4

import pytest

from diana.application.ports import TurnRecord
from diana.infrastructure.db.repositories.traces import SqlTraceStore
from diana.infrastructure.db.repositories.turns import SqlTurnStore


async def _new_turn(session_factory, chat_id: int, *, channel_type: str) -> object:
    """Create a real turn row (pipeline_traces.turn_id has an FK to turns)."""
    store = SqlTurnStore(session_factory)
    return await store.create(
        TurnRecord(
            id=uuid4(), chat_id=chat_id, status="received",
            channel_type=channel_type,
        )
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_store_propagates_atencion_channel_type(session_factory):
    """REQ-ATN-13: atencion turn → trace row persists channel_type='atencion'."""
    store = SqlTraceStore(session_factory)
    turn = await _new_turn(session_factory, 900, channel_type="atencion")

    await store.store(turn.id, "comprehension", {"intent": "help"})

    trace = await store.get_full_trace(turn.id)
    assert trace is not None
    assert trace["channel_type"] == "atencion"
    assert trace["chat_id"] == 900
    assert trace["vip_id"] is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_store_propagates_default_vip_channel_type(session_factory):
    """REQ-ATN-13: VIP turn (default) → trace row keeps channel_type='vip'."""
    from diana.infrastructure.db.repositories.vips import SqlVipStore

    vip_store = SqlVipStore(session_factory)
    vip = await vip_store.add(12345, display_name="Test VIP for trace")

    store = SqlTraceStore(session_factory)
    turn_store = SqlTurnStore(session_factory)
    turn = await turn_store.create(
        TurnRecord(
            id=uuid4(), chat_id=901, status="received",
            vip_id=vip.id, channel_type="vip",
        )
    )

    await store.store(turn.id, "comprehension", {"intent": "sale"})

    trace = await store.get_full_trace(turn.id)
    assert trace is not None
    assert trace["channel_type"] == "vip"  # default preserved (flag OFF)
    assert trace["chat_id"] == 901
    assert trace["vip_id"] == vip.id
