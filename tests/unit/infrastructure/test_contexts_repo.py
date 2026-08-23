"""ContextsRepo — unit tests without live Postgres (AsyncMock fakes)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from diana.infrastructure.db.repositories.contexts import (
    ContextsRepo,
    context_to_dict,
)


def _make_session_factory() -> MagicMock:
    """Build async_sessionmaker-like factory capturing execute/add/commit."""
    session = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[])
    result.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    sf = MagicMock(return_value=cm)
    sf._session = session  # test access
    return sf


def _row(
    *,
    chat_id: int = 100,
    content: dict | None = None,
    vip_id=None,
    expires_at: datetime | None = None,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        vip_id=vip_id,
        chat_id=chat_id,
        content=content or {"tipo": "interpretado", "hechos": {}},
        expires_at=expires_at or (now + timedelta(hours=1)),
        created_at=created_at or now,
    )


def test_context_to_dict_shape() -> None:
    row = _row()
    d = context_to_dict(row)
    assert set(d.keys()) == {
        "id",
        "vip_id",
        "chat_id",
        "content",
        "expires_at",
        "created_at",
    }
    assert d["chat_id"] == 100


@pytest.mark.asyncio
async def test_insert_adds_row_and_commits() -> None:
    sf = _make_session_factory()
    repo = ContextsRepo(sf)
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    await repo.insert(
        chat_id=100,
        content={"tipo": "interpretado", "hechos": {"hora_actual": "06:00"}},
        embedding=[0.1] * 384,
        expires_at=expires_at,
        vip_id=uuid4(),
    )
    sf._session.add.assert_called_once()
    added = sf._session.add.call_args[0][0]
    assert added.chat_id == 100
    assert len(added.embedding) == 384
    assert added.expires_at == expires_at
    sf._session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_find_active_by_chat_returns_rows() -> None:
    sf = _make_session_factory()
    row = _row(chat_id=7)
    sf._session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[row]))))
    )
    repo = ContextsRepo(sf)
    rows = await repo.find_active_by_chat(7)
    assert len(rows) == 1
    assert rows[0]["chat_id"] == 7


@pytest.mark.asyncio
async def test_find_by_similarity_builds_distance_query() -> None:
    sf = _make_session_factory()
    row = _row()
    sf._session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[row]))))
    )
    repo = ContextsRepo(sf)
    rows = await repo.find_by_similarity([0.0] * 384, threshold=0.75)
    assert len(rows) == 1
    assert rows[0]["chat_id"] == 100
    # Ordering/where built on cosine_distance — exercise the generated stmt.
    stmt = sf._session.execute.await_args.args[0]
    assert "<=>" in str(stmt)


@pytest.mark.asyncio
async def test_delete_expired_returns_rowcount() -> None:
    sf = _make_session_factory()
    result = MagicMock()
    result.rowcount = 3
    sf._session.execute = AsyncMock(return_value=result)
    repo = ContextsRepo(sf)
    deleted = await repo.delete_expired()
    assert deleted == 3
    sf._session.commit.assert_awaited()
