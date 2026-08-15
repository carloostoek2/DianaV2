"""EphemeralKnowledgeAugmenter — inject active ephemeral events into retrieved map."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from diana.application.ephemeral_knowledge import EphemeralKnowledgeAugmenter
from diana.application.ports import EphemeralEventRecord
from diana.cognitive.models import IncomingTurn

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _turn(chat_id: int = 100) -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=chat_id, text="hola")


def _event(**kw) -> EphemeralEventRecord:
    data = dict(
        id=uuid4(),
        body="promo del fin de semana",
        start_at=_NOW - timedelta(hours=1),
        end_at=_NOW + timedelta(days=2),
        is_paused=False,
        created_by=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    data.update(kw)
    return EphemeralEventRecord(**data)


class _FakeEphemeralEventStore:
    """In-memory EphemeralEventStore mirroring repo find_active_at semantics."""

    def __init__(self, events: list[EphemeralEventRecord]) -> None:
        self._events = events

    async def find_active_at(self, now: datetime) -> list[EphemeralEventRecord]:
        return [
            e
            for e in self._events
            if not e.is_paused and e.start_at <= now < e.end_at
        ]


def _augmenter(events: list[EphemeralEventRecord], *, now: datetime = _NOW):
    return EphemeralKnowledgeAugmenter(_FakeEphemeralEventStore(events), lambda: now)


@pytest.mark.asyncio
async def test_injects_when_active_events_exist() -> None:
    aug = _augmenter([_event()])
    retrieved: dict = {"knowledge.memory": None}
    out = await aug.augment_retrieved(_turn(), retrieved)
    assert "knowledge.ephemeral" in out
    assert out["knowledge.ephemeral"] == {"eventos": ["promo del fin de semana"]}
    # Original map not mutated
    assert retrieved == {"knowledge.memory": None}
    assert "knowledge.ephemeral" not in retrieved


@pytest.mark.asyncio
async def test_no_active_events_returns_retrieved_unchanged() -> None:
    aug = _augmenter([])
    retrieved: dict = {"knowledge.memory": {"x": 1}}
    out = await aug.augment_retrieved(_turn(), retrieved)
    assert out is retrieved
    assert "knowledge.ephemeral" not in out


@pytest.mark.asyncio
async def test_paused_event_not_injected() -> None:
    aug = _augmenter([_event(is_paused=True)])
    retrieved: dict = {}
    out = await aug.augment_retrieved(_turn(), retrieved)
    assert "knowledge.ephemeral" not in out


@pytest.mark.asyncio
async def test_out_of_window_event_not_injected() -> None:
    # start_at in the future → not active
    future = _augmenter([_event(start_at=_NOW + timedelta(hours=1))])
    out = await future.augment_retrieved(_turn(), {})
    assert "knowledge.ephemeral" not in out

    # end_at in the past → not active
    expired = _augmenter([_event(end_at=_NOW - timedelta(hours=1))])
    out = await expired.augment_retrieved(_turn(), {})
    assert "knowledge.ephemeral" not in out


@pytest.mark.asyncio
async def test_injects_all_active_event_bodies() -> None:
    aug = _augmenter(
        [
            _event(body="promo 2x1"),
            _event(body="cumpleaños de un VIP"),
            _event(body="pausado", is_paused=True),
        ]
    )
    out = await aug.augment_retrieved(_turn(), {})
    assert out["knowledge.ephemeral"] == {
        "eventos": ["promo 2x1", "cumpleaños de un VIP"]
    }
