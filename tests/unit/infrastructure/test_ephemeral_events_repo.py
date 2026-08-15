"""Offline port/repo surface tests for ephemeral_events (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from diana.infrastructure.db.repositories.ephemeral_events import (
    EphemeralEventRepo,
    ephemeral_event_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_ephemeral_event_mapper_pure() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        body="promo del fin de semana",
        start_at=_now(),
        end_at=_now(),
        is_paused=False,
        created_by=42,
        created_at=_now(),
        updated_at=_now(),
    )
    record = ephemeral_event_orm_to_record(row)  # type: ignore[arg-type]
    assert record.id == row.id
    assert record.body == "promo del fin de semana"
    assert record.is_paused is False
    assert record.created_by == 42
    assert record.start_at == row.start_at
    assert record.end_at == row.end_at


def test_ephemeral_event_mapper_nullable_created_by() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        body="x",
        start_at=_now(),
        end_at=_now(),
        is_paused=True,
        created_by=None,
        created_at=_now(),
        updated_at=_now(),
    )
    record = ephemeral_event_orm_to_record(row)  # type: ignore[arg-type]
    assert record.is_paused is True
    assert record.created_by is None


def test_ephemeral_event_repo_surface() -> None:
    sig = inspect.signature(EphemeralEventRepo.__init__)
    assert "session_factory" in sig.parameters
    repo = EphemeralEventRepo(session_factory=object())  # type: ignore[arg-type]
    for name in (
        "create",
        "get",
        "list_all",
        "update",
        "set_paused",
        "terminate_now",
        "delete",
        "find_active_at",
    ):
        assert inspect.iscoroutinefunction(getattr(repo, name)), name
