"""Unit tests for PersonaAdminService (owner-gated, flag-gated, validated)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from diana.application.admin_service import OwnerAuthError
from diana.application.persona_admin_service import PersonaAdminService
from diana.application.ports import PersonaVersionRecord
from diana.cognitive.persona_catalog import load_persona_catalog

OWNER_ID = 123
OTHER_ID = 999


def _now() -> datetime:
    return datetime.now(UTC)


def _valid_catalog() -> dict:
    return load_persona_catalog()


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
    ) -> PersonaVersionRecord:
        record = PersonaVersionRecord(
            id=uuid4(),
            version=version,
            source=source,
            payload=payload,
            created_by=created_by,
            created_at=_now(),
        )
        self.records.append(record)
        self.inserted.append(record)
        return record

    async def list_versions(self) -> list[PersonaVersionRecord]:
        return sorted(self.records, key=lambda r: r.created_at, reverse=True)

    async def get_by_id(self, persona_version_id) -> PersonaVersionRecord | None:
        for record in self.records:
            if record.id == persona_version_id:
                return record
        return None

    async def get_active(self) -> PersonaVersionRecord | None:
        for record in self.records:
            if record.is_active:
                return record
        return None

    async def activate_version(
        self, persona_version_id, *, now: datetime
    ) -> PersonaVersionRecord | None:
        target = await self.get_by_id(persona_version_id)
        if target is None:
            return None
        for record in self.records:
            record.is_active = record.id == persona_version_id
            record.applied_at = (
                now if record.id == persona_version_id else record.applied_at
            )
        return target


def _make_service(
    store: _MemoryPersonaAdminStore, *, enabled: bool = True
) -> PersonaAdminService:
    return PersonaAdminService(
        payload_store=store,  # type: ignore[arg-type]
        feature_persona_admin_enabled=enabled,
        owner_telegram_id=OWNER_ID,
        clock=_now,
    )


@pytest.mark.asyncio
async def test_non_owner_rejected_on_writes() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store)
    with pytest.raises(OwnerAuthError):
        await service.save_persona(OTHER_ID, _valid_catalog())
    with pytest.raises(OwnerAuthError):
        await service.restore(OTHER_ID, uuid4())
    with pytest.raises(OwnerAuthError):
        await service.list_versions(OTHER_ID)
    with pytest.raises(OwnerAuthError):
        await service.save_persona(None, _valid_catalog())
    assert store.inserted == []


@pytest.mark.asyncio
async def test_get_current_persona_flag_off_returns_none() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store, enabled=False)
    await service.save_persona(OWNER_ID, _valid_catalog())
    assert await service.get_current_persona() is None


@pytest.mark.asyncio
async def test_get_current_persona_flag_on_returns_active_payload() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store, enabled=True)
    assert await service.get_current_persona() is None  # nothing active yet
    await service.save_persona(OWNER_ID, _valid_catalog())
    current = await service.get_current_persona()
    assert current is not None
    assert current["voz_configurada"]["persona"] == _valid_catalog()["voz_configurada"]["persona"]


@pytest.mark.asyncio
async def test_invalid_payload_rejected_before_write() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store)
    with pytest.raises(ValueError, match="persona_facts"):
        await service.save_persona(OWNER_ID, {"voz_configurada": {}})
    assert store.inserted == []


@pytest.mark.asyncio
async def test_save_assigns_sequential_versions_and_activates() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store)
    v1 = await service.save_persona(OWNER_ID, _valid_catalog())
    v2 = await service.save_persona(OWNER_ID, _valid_catalog())
    assert (v1.version, v2.version) == (1, 2)
    assert v1.source == "db" and v2.source == "db"
    assert v1.created_by == OWNER_ID and v2.created_by == OWNER_ID
    # save activates immediately → exactly one active (v2)
    active = await store.get_active()
    assert active is not None and active.version == 2


@pytest.mark.asyncio
async def test_restore_reactivates_previous_version() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store)
    v1 = await service.save_persona(OWNER_ID, _valid_catalog())
    await service.save_persona(OWNER_ID, _valid_catalog())
    restored = await service.restore(OWNER_ID, v1.id)
    assert restored is not None and restored.id == v1.id
    assert restored.applied_at is not None
    active = await store.get_active()
    assert active is not None and active.id == v1.id
    assert len([r for r in store.records if r.is_active]) == 1


@pytest.mark.asyncio
async def test_restore_unknown_id_returns_none() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store)
    v1 = await service.save_persona(OWNER_ID, _valid_catalog())
    assert await service.restore(OWNER_ID, uuid4()) is None
    # the active version must remain untouched
    active = await store.get_active()
    assert active is not None and active.id == v1.id


@pytest.mark.asyncio
async def test_roundtrip_save_then_get_current_persona() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store)
    await service.save_persona(OWNER_ID, _valid_catalog())
    current = await service.get_current_persona()
    assert current == _valid_catalog()


class _RaiseOnActivateStore(_MemoryPersonaAdminStore):
    """Store that raises an IntegrityError-like exception on activation/insert."""

    def __init__(self) -> None:
        super().__init__()
        self.raise_on_activate = False
        self.raise_on_insert = False

    async def insert_version(
        self,
        *,
        version: int,
        source: str,
        payload: dict[str, Any],
        created_by: int | None = None,
    ) -> PersonaVersionRecord:
        if self.raise_on_insert:
            raise type("IntegrityError", (Exception,), {})("version conflict")
        return await super().insert_version(
            version=version,
            source=source,
            payload=payload,
            created_by=created_by,
        )

    async def activate_version(
        self, persona_version_id, *, now: datetime
    ) -> PersonaVersionRecord | None:
        if self.raise_on_activate:
            raise type("IntegrityError", (Exception,), {})("activation conflict")
        return await super().activate_version(persona_version_id, now=now)


@pytest.mark.asyncio
async def test_restore_maps_integrity_error_to_value_error() -> None:
    store = _RaiseOnActivateStore()
    service = _make_service(store)
    await service.save_persona(OWNER_ID, _valid_catalog())
    store.raise_on_activate = True
    with pytest.raises(ValueError, match="persona_activation_conflict"):
        await service.restore(OWNER_ID, uuid4())


@pytest.mark.asyncio
async def test_save_maps_version_conflict_to_value_error() -> None:
    store = _RaiseOnActivateStore()
    service = _make_service(store)
    store.raise_on_insert = True
    with pytest.raises(ValueError, match="persona_version_conflict"):
        await service.save_persona(OWNER_ID, _valid_catalog())


@pytest.mark.asyncio
async def test_save_maps_activation_conflict_to_value_error() -> None:
    store = _RaiseOnActivateStore()
    service = _make_service(store)
    store.raise_on_activate = True
    with pytest.raises(ValueError, match="persona_activation_conflict"):
        await service.save_persona(OWNER_ID, _valid_catalog())


@pytest.mark.asyncio
async def test_non_integrity_errors_propagate_raw() -> None:
    class _ExplodingStore(_MemoryPersonaAdminStore):
        async def insert_version(self, **kwargs: Any) -> PersonaVersionRecord:
            raise RuntimeError("db down")

    service = _make_service(_ExplodingStore())
    with pytest.raises(RuntimeError, match="db down"):
        await service.save_persona(OWNER_ID, _valid_catalog())


@pytest.mark.asyncio
async def test_list_versions_owner_returns_newest_first() -> None:
    store = _MemoryPersonaAdminStore()
    service = _make_service(store)
    await service.save_persona(OWNER_ID, _valid_catalog())
    await service.save_persona(OWNER_ID, _valid_catalog())
    versions = await service.list_versions(OWNER_ID)
    assert [v.version for v in versions] == [2, 1]
    assert all(v.created_by == OWNER_ID for v in versions)
