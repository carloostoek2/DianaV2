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
