"""ProfilesRepo writers — unit tests without live Postgres.

Covers pure-path contracts via helpers and source-shape expectations for
VIP-scoped mutators. ORM session behavior is asserted with AsyncMock fakes.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from diana.infrastructure.db.repositories.profiles import (
    ProfilesRepo,
    apply_delete_fact,
    apply_set_fact,
    empty_content,
)


def test_writer_methods_exist_on_profiles_repo() -> None:
    for name in (
        "set_fact",
        "delete_fact",
        "add_note",
        "delete_note",
        "delete_by_vip_id",
    ):
        assert hasattr(ProfilesRepo, name)
        assert callable(getattr(ProfilesRepo, name))


def test_set_fact_pure_path_creates_from_empty() -> None:
    content = apply_set_fact(empty_content(), "city", "BA")
    assert content == {"facts": {"city": "BA"}, "notes": []}


def test_delete_fact_pure_path_missing_key() -> None:
    content = apply_set_fact(empty_content(), "city", "BA")
    out, deleted = apply_delete_fact(content, "missing")
    assert deleted is False
    assert out["facts"] == {"city": "BA"}


def _make_session_factory(row: object | None = None) -> MagicMock:
    """Build async_sessionmaker-like factory capturing add/commit/refresh."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=row)
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


@pytest.mark.asyncio
async def test_set_fact_inserts_when_row_missing() -> None:
    vip_id = uuid4()
    sf = _make_session_factory(row=None)
    repo = ProfilesRepo(sf)

    out = await repo.set_fact(vip_id, "city", "BA")

    assert out["content"]["facts"]["city"] == "BA"
    assert out["tipo"] == "summary"
    assert out["vip_id"] == str(vip_id)
    sf._session.add.assert_called_once()
    added = sf._session.add.call_args[0][0]
    assert list(added.embedding) == [0.0] * 384
    assert added.content == {"facts": {"city": "BA"}, "notes": []}
    sf._session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_set_fact_updates_existing_row_without_reinsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vip_id = uuid4()
    row = SimpleNamespace(
        vip_id=vip_id,
        tipo="summary",
        content={"facts": {"city": "BA"}, "notes": []},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    sf = _make_session_factory(row=row)
    repo = ProfilesRepo(sf)
    # flag_modified needs a real SQLAlchemy instance; stub ORM edge only.
    monkeypatch.setattr(
        "diana.infrastructure.db.repositories.profiles.flag_modified",
        MagicMock(),
    )

    out = await repo.set_fact(vip_id, "city", "MDZ")

    assert out["content"]["facts"]["city"] == "MDZ"
    sf._session.add.assert_not_called()
    assert row.content == {"facts": {"city": "MDZ"}, "notes": []}
    sf._session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_fact_returns_none_when_no_row() -> None:
    vip_id = uuid4()
    sf = _make_session_factory(row=None)
    repo = ProfilesRepo(sf)
    out = await repo.delete_fact(vip_id, "city")
    assert out is None


@pytest.mark.asyncio
async def test_delete_note_returns_none_when_oob() -> None:
    vip_id = uuid4()
    row = SimpleNamespace(
        vip_id=vip_id,
        tipo="summary",
        content={"facts": {}, "notes": [{"date": "2026-01-01", "text": "only"}]},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    sf = _make_session_factory(row=row)
    repo = ProfilesRepo(sf)
    out = await repo.delete_note(vip_id, 99)
    assert out is None
    sf._session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_fact_rejects_empty_key_without_session_write() -> None:
    vip_id = uuid4()
    sf = _make_session_factory(row=None)
    repo = ProfilesRepo(sf)
    with pytest.raises(ValueError):
        await repo.set_fact(vip_id, "", "v")
    sf.assert_not_called()


@pytest.mark.asyncio
async def test_delete_by_vip_id_missing_returns_false_no_delete() -> None:
    vip_id = uuid4()
    sf = _make_session_factory(row=None)
    sf._session.delete = AsyncMock()
    repo = ProfilesRepo(sf)

    deleted = await repo.delete_by_vip_id(vip_id)

    assert deleted is False
    sf._session.delete.assert_not_awaited()
    sf._session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_by_vip_id_existing_deletes_and_commits() -> None:
    vip_id = uuid4()
    row = SimpleNamespace(vip_id=vip_id, content={"facts": {}, "notes": []})
    sf = _make_session_factory(row=row)
    sf._session.delete = AsyncMock()
    repo = ProfilesRepo(sf)

    deleted = await repo.delete_by_vip_id(vip_id)

    assert deleted is True
    sf._session.delete.assert_awaited_once_with(row)
    sf._session.commit.assert_awaited()


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [float(ord(c)) for c in text[:8]] + [0.0] * 376


@pytest.mark.asyncio
async def test_set_fact_with_embedder_writes_real_embedding() -> None:
    """The vector feature of the profile store: with an embedder injected the
    embedding reflects the content instead of zeros."""
    vip_id = uuid4()
    sf = _make_session_factory(row=None)
    repo = ProfilesRepo(sf, embedder=FakeEmbedder())

    out = await repo.set_fact(vip_id, "city", "CDMX")

    sf._session.add.assert_called_once()
    added = sf._session.add.call_args[0][0]
    # Real (non-zero) embedding of the profile content.
    assert any(x != 0.0 for x in added.embedding)
    assert len(added.embedding) == 384
    assert out["content"]["facts"]["city"] == "CDMX"


@pytest.mark.asyncio
async def test_find_by_similarity_returns_matching_rows() -> None:
    vip_id = uuid4()
    row = SimpleNamespace(
        vip_id=vip_id,
        tipo="summary",
        content={"facts": {"city": "CDMX"}, "notes": []},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    sf = _make_session_factory()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[row])
    sf._session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=scalars))
    )
    repo = ProfilesRepo(sf)

    rows = await repo.find_by_similarity([0.0] * 384, threshold=0.7)

    assert len(rows) == 1
    assert rows[0]["content"]["facts"]["city"] == "CDMX"
    stmt = sf._session.execute.await_args.args[0]
    assert "<=>" in str(stmt)
