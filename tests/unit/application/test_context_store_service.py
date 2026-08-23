"""Unit tests for ContextStoreService (REQ-MEM-06 post-turn writer)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from diana.application.context_store_service import ContextStoreService


class FakeTurn:
    def __init__(self, *, chat_id: int, vip_id: UUID | None = None) -> None:
        self.chat_id = chat_id
        self.vip_id = vip_id


class FakeTurnStore:
    def __init__(self, turn) -> None:
        self._turn = turn

    async def get(self, turn_id: UUID):
        return self._turn


class FakeHistory:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self._messages = messages or []

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]:
        return self._messages


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [float(ord(c)) for c in text[:8]] + [0.0] * 376


class RecordingContexts:
    def __init__(self) -> None:
        self.inserts: list[dict] = []

    async def insert(
        self,
        *,
        chat_id: int,
        content: dict,
        embedding: list[float],
        expires_at: datetime,
        vip_id: UUID | None = None,
    ) -> dict:
        self.inserts.append(
            {
                "chat_id": chat_id,
                "content": content,
                "embedding": embedding,
                "expires_at": expires_at,
                "vip_id": vip_id,
            }
        )
        return {"id": "1", **self.inserts[-1]}


@pytest.mark.asyncio
async def test_record_post_turn_disabled_flag_off() -> None:
    store = ContextStoreService(
        feature_context_enabled=False,
        embedder=FakeEmbedder(),
        history=FakeHistory(),
        contexts=RecordingContexts(),
        turns=FakeTurnStore(FakeTurn(chat_id=100)),
        ttl_hours=24,
    )
    assert await store.record_post_turn(uuid4()) is False


@pytest.mark.asyncio
async def test_record_post_turn_writes_interpreted_snapshot() -> None:
    contexts = RecordingContexts()
    history = FakeHistory(
        [
            {"role": "vip", "text": "hola", "timestamp": "2026-07-01T09:00:00+00:00"},
        ]
    )
    store = ContextStoreService(
        feature_context_enabled=True,
        embedder=FakeEmbedder(),
        history=history,
        contexts=contexts,
        turns=FakeTurnStore(FakeTurn(chat_id=100, vip_id=uuid4())),
        ttl_hours=24,
    )
    turn_id = uuid4()
    assert await store.record_post_turn(turn_id) is True
    assert len(contexts.inserts) == 1
    ins = contexts.inserts[0]
    assert ins["chat_id"] == 100
    assert ins["content"]["tipo"] == "interpretado"
    hechos = ins["content"]["hechos"]
    assert set(hechos.keys()) == {
        "waiting_for_reply_since",
        "is_first_message_of_day",
        "dia_semana",
        "hora_actual",
    }
    # Expiry is in the future (TTL 24h).
    assert ins["expires_at"] > datetime.now(UTC)
    # Non-zero embedding from the fake embedder.
    assert any(x != 0.0 for x in ins["embedding"])


@pytest.mark.asyncio
async def test_record_post_turn_missing_turn_skips() -> None:
    store = ContextStoreService(
        feature_context_enabled=True,
        embedder=FakeEmbedder(),
        history=FakeHistory(),
        contexts=RecordingContexts(),
        turns=FakeTurnStore(None),
        ttl_hours=24,
    )
    assert await store.record_post_turn(uuid4()) is False


@pytest.mark.asyncio
async def test_record_post_turn_never_raises() -> None:
    class BoomHistory:
        async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]:
            raise RuntimeError("history boom")

    store = ContextStoreService(
        feature_context_enabled=True,
        embedder=FakeEmbedder(),
        history=BoomHistory(),
        contexts=RecordingContexts(),
        turns=FakeTurnStore(FakeTurn(chat_id=100)),
        ttl_hours=24,
    )
    assert await store.record_post_turn(uuid4()) is False
