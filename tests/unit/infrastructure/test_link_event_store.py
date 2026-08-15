"""Offline port/repo surface + in-memory behavior tests for link_events."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from diana.application.memory import InMemoryLinkEventStore
from diana.application.ports import LinkEventRecord
from diana.infrastructure.db.repositories.link_events import (
    SqlLinkEventStore,
    link_event_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _full_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        event_id="evt-1",
        user_id=12345,
        username="@ana",
        channel_id=777,
        channel_name="Canal VIP",
        reason="quitó el acceso",
        vip_id=uuid4(),
        state="pending",
        decision_at=None,
        created_at=_now(),
    )


def test_link_event_mapper_pure() -> None:
    row = _full_row()
    record = link_event_orm_to_record(row)  # type: ignore[arg-type]
    assert record.id == row.id
    assert record.event_id == "evt-1"
    assert record.user_id == 12345
    assert record.username == "@ana"
    assert record.channel_id == 777
    assert record.channel_name == "Canal VIP"
    assert record.reason == "quitó el acceso"
    assert record.vip_id == row.vip_id
    assert record.state == "pending"
    assert record.decision_at is None
    assert record.created_at == row.created_at


def test_link_event_mapper_nullable_fields() -> None:
    row = SimpleNamespace(
        id=None,
        event_id="evt-2",
        user_id=1,
        username=None,
        channel_id=None,
        channel_name=None,
        reason="r",
        vip_id=None,
        state="ignored_not_vip",
        decision_at=None,
        created_at=None,
    )
    record = link_event_orm_to_record(row)  # type: ignore[arg-type]
    assert record.id is None
    assert record.username is None
    assert record.channel_id is None
    assert record.channel_name is None
    assert record.vip_id is None
    assert record.decision_at is None
    assert record.created_at is None


def test_sql_link_event_store_surface() -> None:
    sig = inspect.signature(SqlLinkEventStore.__init__)
    assert "session_factory" in sig.parameters
    store = SqlLinkEventStore(session_factory=object())  # type: ignore[arg-type]
    for name in ("create", "get_by_event_id", "set_state"):
        assert inspect.iscoroutinefunction(getattr(store, name)), name


@pytest.mark.asyncio
async def test_in_memory_create_fills_id_and_created_at() -> None:
    store = InMemoryLinkEventStore()
    record, created = await store.create(
        LinkEventRecord(
            event_id="evt-1",
            user_id=12345,
            username="@ana",
            channel_id=777,
            channel_name="Canal VIP",
            reason="quitó el acceso",
            vip_id=None,
            state="pending",
        )
    )
    assert created is True
    assert isinstance(record.id, UUID)
    assert record.created_at is not None


@pytest.mark.asyncio
async def test_in_memory_dedup_returns_existing_and_keeps_state() -> None:
    store = InMemoryLinkEventStore()
    first, created = await store.create(
        LinkEventRecord(event_id="evt-1", user_id=12345, reason="r", state="pending")
    )
    assert created is True
    await store.set_state("evt-1", "notified")
    second, created = await store.create(
        LinkEventRecord(event_id="evt-1", user_id=12345, reason="r", state="pending")
    )
    assert created is False
    assert second.event_id == first.event_id
    assert second.state == "notified"


@pytest.mark.asyncio
async def test_in_memory_get_by_event_id() -> None:
    store = InMemoryLinkEventStore()
    assert await store.get_by_event_id("missing") is None
    await store.create(LinkEventRecord(event_id="evt-1", user_id=1, reason="r"))
    rec = await store.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.event_id == "evt-1"


@pytest.mark.asyncio
async def test_in_memory_set_state_persists_decision_at() -> None:
    store = InMemoryLinkEventStore()
    await store.create(LinkEventRecord(event_id="evt-1", user_id=1, reason="r"))
    decision_at = _now()
    await store.set_state("evt-1", "decided_expel", decision_at=decision_at)
    rec = await store.get_by_event_id("evt-1")
    assert rec is not None
    assert rec.state == "decided_expel"
    assert rec.decision_at == decision_at


@pytest.mark.asyncio
async def test_in_memory_set_state_unknown_event_raises_key_error() -> None:
    store = InMemoryLinkEventStore()
    with pytest.raises(KeyError):
        await store.set_state("missing", "decided_expel")
