"""E2E: MessageHistory SQL repository."""
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
