"""Offline port/repo surface tests for persona_versions (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from diana.application.ports import (
    PersonaAdminStore,
    PersonaVersionRecord,
)
from diana.infrastructure.db.repositories.persona_versions import (
    PersonaVersionRepo,
    persona_version_orm_to_record,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _record(
    version: int = 1, *, is_active: bool = False, channel_type: str = "vip"
) -> PersonaVersionRecord:
    return PersonaVersionRecord(
        id=uuid4(),
        version=version,
        source="db",
        payload={"voz_configurada": {"persona": "x", "reglas_estilo": ["r"]}},
        is_active=is_active,
        created_by=123,
        created_at=_now(),
        applied_at=None,
        channel_type=channel_type,
    )


def test_persona_ports_importable_and_extra_forbid() -> None:
    assert PersonaAdminStore is not None
    rec = _record()
    assert rec.version == 1
    assert rec.source == "db"
    with pytest.raises(ValueError):
        PersonaVersionRecord(
            id=uuid4(),
            version=1,
            source="db",
            payload={},
            created_at=_now(),
            unexpected="x",
        )


def test_orm_to_record_mapper_pure() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        version=3,
        source="db",
        payload={"a": 1},
        is_active=True,
        created_by=42,
        created_at=_now(),
        applied_at=None,
        channel_type="atencion",
    )
    record = persona_version_orm_to_record(row)  # type: ignore[arg-type]
    assert record.version == 3
    assert record.is_active is True
    assert record.created_by == 42
    assert record.applied_at is None
    assert record.channel_type == "atencion"


def test_persona_version_repo_surface() -> None:
    sig = inspect.signature(PersonaVersionRepo.__init__)
    assert "session_factory" in sig.parameters
    repo = PersonaVersionRepo(session_factory=object())  # type: ignore[arg-type]
    for name in (
        "insert_version",
        "list_versions",
        "get_by_id",
        "get_active",
        "activate_version",
    ):
        method = getattr(repo, name)
        assert inspect.iscoroutinefunction(method), name


def test_protocol_method_names_match_repo() -> None:
    protocol_names = set(
        getattr(PersonaAdminStore, "__protocol_attrs__", set())
    )
    repo_names = {
        name
        for name in ("insert_version", "list_versions", "get_by_id", "get_active", "activate_version")
    }
    assert protocol_names == repo_names
    assert isinstance(PersonaVersionRepo, type)
    # duck-typing: repo instance satisfies the protocol at runtime
    assert isinstance(
        PersonaVersionRepo(session_factory=object()),  # type: ignore[arg-type]
        PersonaAdminStore,
    )


class _MemoryPersonaAdminStore:
    """In-memory PersonaAdminStore (unit, no Postgres)."""

    def __init__(self) -> None:
        self.records: list[PersonaVersionRecord] = []
        self.inserted: list[PersonaVersionRecord] = []

    async def insert_version(
        self,
        *,
        version: int,
        source: str,
        payload: dict,
        created_by: int | None = None,
        channel_type: str = "vip",
    ) -> PersonaVersionRecord:
        # The ``uq_persona_versions_version`` index is GLOBAL (PLAN A2): a
        # duplicate version number across ANY channel must fail, exactly like
        # Postgres, so a per-channel counter bug cannot hide behind the fake.
        if any(r.version == version for r in self.records):
            raise type("IntegrityError", (Exception,), {})("version conflict")
        record = PersonaVersionRecord(
            id=uuid4(),
            version=version,
            source=source,
            payload=payload,
            created_by=created_by,
            created_at=_now(),
            channel_type=channel_type,
        )
        self.records.append(record)
        self.inserted.append(record)
        return record

    async def list_versions(
        self, *, channel_type: str | None = None
    ) -> list[PersonaVersionRecord]:
        records = (
            self.records
            if channel_type is None
            else [r for r in self.records if r.channel_type == channel_type]
        )
        return sorted(
            records,
            key=lambda r: (r.created_at, r.version),
            reverse=True,
        )

    async def get_by_id(self, persona_version_id) -> PersonaVersionRecord | None:
        for record in self.records:
            if record.id == persona_version_id:
                return record
        return None

    async def get_active(
        self, *, channel_type: str = "vip"
    ) -> PersonaVersionRecord | None:
        for record in self.records:
            if record.is_active and record.channel_type == channel_type:
                return record
        return None

    async def activate_version(
        self,
        persona_version_id,
        *,
        now: datetime,
        channel_type: str = "vip",
    ) -> PersonaVersionRecord | None:
        target = await self.get_by_id(persona_version_id)
        if target is None or target.channel_type != channel_type:
            return None
        # Mirror the repo UPDATE: only rows in this channel are flipped; rows
        # from other channels are never touched.
        for record in self.records:
            if record.channel_type != channel_type:
                continue
            record.is_active = record.id == persona_version_id
            record.applied_at = (
                now if record.id == persona_version_id else record.applied_at
            )
        return target


@pytest.mark.asyncio
async def test_memory_store_activation_semantics() -> None:
    store = _MemoryPersonaAdminStore()
    v1 = await store.insert_version(version=1, source="db", payload={"a": 1}, created_by=1)
    v2 = await store.insert_version(version=2, source="db", payload={"a": 2}, created_by=1)

    assert await store.get_active() is None
    assert v1.is_active is False and v2.is_active is False

    now = _now()
    active = await store.activate_version(v2.id, now=now)
    assert active is not None and active.id == v2.id
    assert await store.get_active() is not None
    assert (await store.get_active()).id == v2.id
    # exactly one active after re-activation of v1
    await store.activate_version(v1.id, now=now)
    assert (await store.get_active()).id == v1.id
    actives = [r for r in store.records if r.is_active]
    assert len(actives) == 1

    assert await store.activate_version(uuid4(), now=now) is None


@pytest.mark.asyncio
async def test_memory_store_unknown_activation_keeps_active() -> None:
    """Mirror of the fixed repo semantics: unknown id must not deactivate the active row."""
    store = _MemoryPersonaAdminStore()
    v1 = await store.insert_version(version=1, source="db", payload={"a": 1}, created_by=1)
    await store.activate_version(v1.id, now=_now())
    assert await store.activate_version(uuid4(), now=_now()) is None
    active = await store.get_active()
    assert active is not None and active.id == v1.id


@pytest.mark.asyncio
async def test_memory_store_list_versions_newest_first() -> None:
    """Ordering contract (created_at DESC, version DESC) exercised on the fake."""
    store = _MemoryPersonaAdminStore()
    base = _now()
    older = base.replace(hour=1)
    newer = base.replace(hour=2)
    newest = base.replace(hour=3)
    v1 = await store.insert_version(version=1, source="db", payload={}, created_by=1)
    v1.created_at = older
    v2 = await store.insert_version(version=2, source="db", payload={}, created_by=1)
    v2.created_at = newest
    v3 = await store.insert_version(version=3, source="db", payload={}, created_by=1)
    v3.created_at = newer

    versions = await store.list_versions()
    assert [v.version for v in versions] == [2, 3, 1]


@pytest.mark.asyncio
async def test_memory_store_list_versions_tiebreak_by_version() -> None:
    """Tie on created_at resolves by version DESC (mirror of the repo ORDER BY)."""
    store = _MemoryPersonaAdminStore()
    same = _now()
    v1 = await store.insert_version(version=1, source="db", payload={}, created_by=1)
    v1.created_at = same
    v3 = await store.insert_version(version=3, source="db", payload={}, created_by=1)
    v3.created_at = same
    v2 = await store.insert_version(version=2, source="db", payload={}, created_by=1)
    v2.created_at = same

    versions = await store.list_versions()
    assert [v.version for v in versions] == [3, 2, 1]


def test_activate_version_source_keeps_exists_guard() -> None:
    """Source pin: the swap must keep the EXISTS guard (unknown-id no-op)."""
    source = inspect.getsource(PersonaVersionRepo.activate_version)
    assert ".exists()" in source
    assert "& exists" in source
    # channel scoping must be part of the exists guard (cross-channel no-op)
    assert "PersonaVersion.channel_type == channel_type" in source
    # S1: the post-UPDATE re-fetch must verify the channel before returning,
    # so a cross-channel id (zero rows updated) returns None, not the record.
    assert "record.channel_type != channel_type" in source
    assert "return None" in source


@pytest.mark.asyncio
async def test_activation_scoped_by_channel() -> None:
    """One active row per channel; versions are GLOBAL (vip v1, atencion v2)."""
    store = _MemoryPersonaAdminStore()
    vip = await store.insert_version(
        version=1, source="db", payload={"a": 1}, created_by=1, channel_type="vip"
    )
    atencion = await store.insert_version(
        version=2,
        source="db",
        payload={"a": 2},
        created_by=1,
        channel_type="atencion",
    )
    await store.activate_version(vip.id, now=_now(), channel_type="vip")
    await store.activate_version(atencion.id, now=_now(), channel_type="atencion")

    vip_active = await store.get_active(channel_type="vip")
    atencion_active = await store.get_active(channel_type="atencion")
    assert vip_active is not None and vip_active.id == vip.id
    assert atencion_active is not None and atencion_active.id == atencion.id
    # both active rows coexist (different channels)
    assert len([r for r in store.records if r.is_active]) == 2


@pytest.mark.asyncio
async def test_activation_cross_channel_id_is_noop() -> None:
    """An id belonging to another channel must not deactivate the active row."""
    store = _MemoryPersonaAdminStore()
    vip = await store.insert_version(
        version=1, source="db", payload={"a": 1}, created_by=1, channel_type="vip"
    )
    atencion = await store.insert_version(
        version=2,
        source="db",
        payload={"a": 2},
        created_by=1,
        channel_type="atencion",
    )
    await store.activate_version(vip.id, now=_now(), channel_type="vip")
    # try to activate the atencion row scoped to vip → no-op, vip stays active
    assert await store.activate_version(atencion.id, now=_now(), channel_type="vip") is None
    active = await store.get_active(channel_type="vip")
    assert active is not None and active.id == vip.id
