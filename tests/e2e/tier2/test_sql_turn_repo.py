"""E2E: SqlTurnStore CRUD against real PostgreSQL."""
import pytest
from uuid import uuid4
from diana.infrastructure.db.repositories.turns import SqlTurnStore
from diana.application.ports import TurnRecord


@pytest.mark.db
@pytest.mark.asyncio
async def test_create_turn_returns_record(session_factory):
    repo = SqlTurnStore(session_factory)
    turn = TurnRecord(
        id=uuid4(), chat_id=100,
        status="received",
    )
    created = await repo.create(turn)
    assert created.id == turn.id
    assert created.chat_id == 100
    assert created.status == "received"


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_turn_by_id(session_factory):
    repo = SqlTurnStore(session_factory)
    turn_id = uuid4()
    turn = TurnRecord(id=turn_id, chat_id=42, status="received")
    await repo.create(turn)
    stored = await repo.get(turn_id)
    assert stored is not None
    assert stored.chat_id == 42


@pytest.mark.db
@pytest.mark.asyncio
async def test_transition_updates_status(session_factory):
    repo = SqlTurnStore(session_factory)
    turn_id = uuid4()
    turn = TurnRecord(id=turn_id, chat_id=50, status="received")
    await repo.create(turn)
    updated = await repo.transition(turn_id, "pending_approval")
    assert updated.status == "pending_approval"


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_non_terminal_filters_by_chat(session_factory):
    repo = SqlTurnStore(session_factory)
    t1 = TurnRecord(id=uuid4(), chat_id=77, status="received")
    t2 = TurnRecord(id=uuid4(), chat_id=77, status="pending_approval")
    t3 = TurnRecord(id=uuid4(), chat_id=88, status="received")
    await repo.create(t1)
    await repo.create(t2)
    await repo.create(t3)

    turns_77 = await repo.list_non_terminal(77)
    assert len(turns_77) == 2
    turns_88 = await repo.list_non_terminal(88)
    assert len(turns_88) == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(session_factory):
    repo = SqlTurnStore(session_factory)
    stored = await repo.get(uuid4())
    assert stored is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_create_preserves_vip_id(session_factory):
    from diana.infrastructure.db.repositories.vips import SqlVipStore
    vip_store = SqlVipStore(session_factory)
    vip = await vip_store.add(12345, display_name="Test VIP for turn")

    repo = SqlTurnStore(session_factory)
    turn_id = uuid4()
    turn = TurnRecord(id=turn_id, chat_id=10, status="received", vip_id=vip.id)
    await repo.create(turn)
    stored = await repo.get(turn_id)
    assert stored.vip_id == vip.id
