"""E2E: SqlTurnStore CRUD against real PostgreSQL."""
import pytest
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from sqlalchemy import text
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


async def _create_vip(session_factory, telegram_user_id: int):
    from diana.infrastructure.db.repositories.vips import SqlVipStore

    vip_store = SqlVipStore(session_factory)
    return await vip_store.add(telegram_user_id, display_name="Synthesis VIP")


async def _set_turn_created_at(session_factory, turn_id, when: datetime) -> None:
    """Rewind a turn's created_at for activity-window assertions (no API for it)."""
    async with session_factory() as session:
        await session.execute(
            text("UPDATE turns SET created_at = :when WHERE id = :tid"),
            {"when": when, "tid": turn_id},
        )
        await session.commit()


@pytest.mark.db
@pytest.mark.asyncio
async def test_count_messages_since_filters_vip_channel_and_since(session_factory):
    """A2: one message = one 'vip'-channel turn; edits never create a new turn."""
    vip = await _create_vip(session_factory, 9201)
    repo = SqlTurnStore(session_factory)
    t1 = await repo.create(
        TurnRecord(id=uuid4(), chat_id=9201, status="received", vip_id=vip.id)
    )
    t2 = await repo.create(
        TurnRecord(id=uuid4(), chat_id=9201, status="received", vip_id=vip.id)
    )
    # An atencion-channel turn of the SAME vip must NOT count.
    await repo.create(
        TurnRecord(
            id=uuid4(), chat_id=9201, status="received",
            vip_id=vip.id, channel_type="atencion",
        )
    )
    assert await repo.count_messages_since(vip.id, since=None) == 2

    mid = datetime.now(UTC) - timedelta(minutes=5)
    await _set_turn_created_at(session_factory, t1.id, mid - timedelta(minutes=10))
    await _set_turn_created_at(session_factory, t2.id, mid)
    # Fix round: the boundary is INCLUSIVE (>=), matching memories/staging —
    # t2.created_at == mid IS counted.
    assert await repo.count_messages_since(vip.id, since=mid) == 1
    assert await repo.count_messages_since(vip.id, since=mid - timedelta(minutes=1)) == 1
    assert await repo.count_messages_since(vip.id, since=mid - timedelta(minutes=11)) == 2


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_vips_with_activity_older_than_filters_and_orders(session_factory):
    """Only VIPs whose newest 'vip' turn predates the cutoff, newest first.

    Fix round (S11): membership-based assertions instead of exact-set equality
    on the shared session-scoped DB — other tests' aged VIPs may also satisfy
    the cutoff, so we assert OUR aged VIP is present and OUR fresh one is not.
    """
    repo = SqlTurnStore(session_factory)
    now = datetime.now(UTC)
    old_cut = now - timedelta(days=5)

    old_vip = await _create_vip(session_factory, 9202)
    await _set_turn_created_at(
        session_factory,
        (await repo.create(TurnRecord(id=uuid4(), chat_id=9202, status="received", vip_id=old_vip.id))).id,
        now - timedelta(days=10),
    )
    fresh_vip = await _create_vip(session_factory, 9203)
    await _set_turn_created_at(
        session_factory,
        (await repo.create(TurnRecord(id=uuid4(), chat_id=9203, status="received", vip_id=fresh_vip.id))).id,
        now - timedelta(days=1),
    )

    rows = await repo.list_vips_with_activity_older_than(old_cut)
    by_id = {vip_id: last for vip_id, last in rows}
    assert old_vip.id in by_id  # our aged VIP is returned
    assert fresh_vip.id not in by_id  # our fresh VIP is not
    last = by_id[old_vip.id]
    assert last is not None and last < old_cut  # newest activity predates the cutoff
    # Sanity: the returned last-activity is the aged turn's created_at.
    assert abs((last - (now - timedelta(days=10))).total_seconds()) < 5


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_vips_with_activity_older_than_respects_limit(session_factory):
    repo = SqlTurnStore(session_factory)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=3)
    for uid in (9204, 9205, 9206):
        vip = await _create_vip(session_factory, uid)
        await _set_turn_created_at(
            session_factory,
            (await repo.create(TurnRecord(id=uuid4(), chat_id=uid, status="received", vip_id=vip.id))).id,
            now - timedelta(days=10),
        )
    rows = await repo.list_vips_with_activity_older_than(cutoff, limit=2)
    assert len(rows) == 2


@pytest.mark.db
@pytest.mark.asyncio
async def test_create_roundtrips_atencion_channel_type(session_factory):
    """F4: atencion turns persist channel_type='atencion'; VIP default 'vip'."""
    repo = SqlTurnStore(session_factory)

    atencion_id = uuid4()
    atencion = TurnRecord(
        id=atencion_id, chat_id=900, status="received", channel_type="atencion"
    )
    await repo.create(atencion)
    stored = await repo.get(atencion_id)
    assert stored is not None
    assert stored.channel_type == "atencion"

    vip_id = uuid4()
    vip_turn = TurnRecord(id=vip_id, chat_id=901, status="received")
    await repo.create(vip_turn)
    stored_vip = await repo.get(vip_id)
    assert stored_vip is not None
    assert stored_vip.channel_type == "vip"  # default preserved (flag OFF)
