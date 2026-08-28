"""E2E: MessageHistory SQL repository."""
from datetime import UTC, datetime

import pytest

from diana.infrastructure.db.repositories.history import SqlMessageHistoryRepo


@pytest.mark.db
@pytest.mark.asyncio
async def test_append_and_get_recent(session_factory):
    repo = SqlMessageHistoryRepo(session_factory)
    await repo.append(chat_id=200, role="vip", text="mensaje 1", telegram_message_id=1)
    await repo.append(chat_id=200, role="owner", text="respuesta", telegram_message_id=2)

    recent = await repo.get_recent(chat_id=200, limit=10)
    assert len(recent) == 2
    assert recent[0]["role"] == "vip"
    assert recent[1]["role"] == "owner"


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_recent_respects_limit(session_factory):
    repo = SqlMessageHistoryRepo(session_factory)
    for i in range(5):
        await repo.append(chat_id=300, role="vip", text=f"msg {i}", telegram_message_id=i)

    recent = await repo.get_recent(chat_id=300, limit=3)
    assert len(recent) == 3


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_recent_empty_chat(session_factory):
    repo = SqlMessageHistoryRepo(session_factory)
    recent = await repo.get_recent(chat_id=999, limit=5)
    assert recent == []


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_all_returns_all_chronological(session_factory):
    repo = SqlMessageHistoryRepo(session_factory)
    base = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    # Append out of chronological order on purpose: list_all must sort oldest first.
    await repo.append(
        chat_id=400, role="vip", text="tercero",
        telegram_message_id=3, timestamp=base.replace(hour=12),
    )
    await repo.append(
        chat_id=400, role="owner", text="primero",
        telegram_message_id=1, timestamp=base.replace(hour=10),
    )
    await repo.append(
        chat_id=400, role="vip", text="segundo",
        telegram_message_id=2, timestamp=base.replace(hour=11),
    )

    all_msgs = await repo.list_all(chat_id=400, page_size=2)
    assert len(all_msgs) == 3
    assert [m["text"] for m in all_msgs] == ["primero", "segundo", "tercero"]
    assert [m["role"] for m in all_msgs] == ["owner", "vip", "vip"]
    assert all("timestamp" in m for m in all_msgs)


@pytest.mark.db
@pytest.mark.asyncio
async def test_list_all_empty_chat(session_factory):
    repo = SqlMessageHistoryRepo(session_factory)
    assert await repo.list_all(chat_id=998, page_size=2) == []


@pytest.mark.db
@pytest.mark.asyncio
async def test_append_missing_skips_existing_ids(session_factory):
    """Seed bug: pre-existing rows (atencion/system) must not block the import;
    rows whose telegram id is already stored are skipped, missing ones added."""
    repo = SqlMessageHistoryRepo(session_factory)
    base = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    await repo.append(
        chat_id=500, role="vip", text="ya guardado", telegram_message_id=1
    )
    added = await repo.append_missing(
        chat_id=500,
        rows=[
            ("vip", "previo 1", 100, base.replace(hour=9)),
            ("owner", "previo 2", 101, base.replace(hour=9, minute=5)),
            ("vip", "ya guardado", 1, base.replace(hour=10)),  # duplicate id
        ],
    )
    assert added == 2
    recent = await repo.get_recent(chat_id=500, limit=10)
    assert len(recent) == 3
    assert [r["text"] for r in recent] == ["previo 1", "previo 2", "ya guardado"]
    assert [r["text"] for r in recent].count("ya guardado") == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_append_missing_idempotent_and_chat_scoped(session_factory):
    repo = SqlMessageHistoryRepo(session_factory)
    base = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    rows = [("vip", "a", 1, base), ("owner", "b", 2, base.replace(minute=1))]
    assert await repo.append_missing(chat_id=600, rows=rows) == 2
    assert await repo.append_missing(chat_id=600, rows=rows) == 0
    assert await repo.append_missing(chat_id=600, rows=[("vip", "a", 1, base)]) == 0
    # Same ids in another chat are unrelated — they must be appended there.
    assert await repo.append_missing(chat_id=601, rows=rows) == 2
    assert len(await repo.get_recent(chat_id=600, limit=10)) == 2
    assert len(await repo.get_recent(chat_id=601, limit=10)) == 2
