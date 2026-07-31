"""VIP history upsert — edits replace text, never duplicate message ids."""

from __future__ import annotations

import pytest

from diana.application.memory import InMemoryMessageHistoryWriter


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates_same_message_id() -> None:
    h = InMemoryMessageHistoryWriter()
    assert (
        await h.upsert_vip_message(10, text="original", telegram_message_id=100)
        == "inserted"
    )
    assert (
        await h.upsert_vip_message(10, text="edited final", telegram_message_id=100)
        == "updated"
    )
    recent = await h.get_recent(10, limit=20)
    assert len(recent) == 1
    assert recent[0]["text"] == "edited final"
    assert recent[0]["telegram_message_id"] == 100
    assert recent[0]["role"] == "vip"


@pytest.mark.asyncio
async def test_upsert_dedupes_accidental_duplicate_ids() -> None:
    h = InMemoryMessageHistoryWriter()
    await h.append(10, role="vip", text="a", telegram_message_id=5)
    await h.append(10, role="vip", text="a2", telegram_message_id=5)
    await h.upsert_vip_message(10, text="clean", telegram_message_id=5)
    recent = await h.get_recent(10, limit=20)
    assert len(recent) == 1
    assert recent[0]["text"] == "clean"


@pytest.mark.asyncio
async def test_upsert_none_id_always_inserts() -> None:
    h = InMemoryMessageHistoryWriter()
    await h.upsert_vip_message(1, text="x", telegram_message_id=None)
    await h.upsert_vip_message(1, text="y", telegram_message_id=None)
    assert len(await h.get_recent(1, limit=10)) == 2
