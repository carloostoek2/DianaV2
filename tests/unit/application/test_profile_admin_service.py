"""ProfileAdminService — owner-gated real VIP profile write (unit, no DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from diana.application.admin_service import OwnerAuthError
from diana.application.memory import InMemoryVipStore
from diana.application.profile_admin_service import ProfileAdminService
from diana.infrastructure.db.repositories.profiles import (
    apply_add_note,
    apply_delete_fact,
    apply_delete_note,
    apply_set_fact,
    empty_content,
    is_hollow_content,
    normalize_content,
)

OWNER = 999001
OTHER = 111


class FakeProfilesRepo:
    """In-memory profiles store mirroring ProfilesRepo write contracts."""

    def __init__(self) -> None:
        self.rows: dict[UUID, dict] = {}

    async def get_by_vip_id(self, vip_id: UUID) -> dict | None:
        content = self.rows.get(vip_id)
        if content is None:
            return None
        return {
            "vip_id": str(vip_id),
            "tipo": "summary",
            "content": dict(content),
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    async def set_fact(self, vip_id: UUID, key: str, value: str) -> dict:
        base = self.rows.get(vip_id) or empty_content()
        self.rows[vip_id] = apply_set_fact(base, key, value)
        return await self.get_by_vip_id(vip_id)  # type: ignore[return-value]

    async def delete_fact(self, vip_id: UUID, key: str) -> dict | None:
        if vip_id not in self.rows:
            return None
        new_content, _ = apply_delete_fact(self.rows[vip_id], key)
        self.rows[vip_id] = new_content
        return await self.get_by_vip_id(vip_id)

    async def add_note(
        self, vip_id: UUID, text: str, *, date: str | None = None
    ) -> dict:
        note_date = date or "2026-07-27"
        base = self.rows.get(vip_id) or empty_content()
        self.rows[vip_id] = apply_add_note(base, text, note_date)
        return await self.get_by_vip_id(vip_id)  # type: ignore[return-value]

    async def delete_note(self, vip_id: UUID, index: int) -> dict | None:
        if vip_id not in self.rows:
            return None
        new_content, deleted = apply_delete_note(self.rows[vip_id], index)
        if not deleted:
            return None
        self.rows[vip_id] = new_content
        return await self.get_by_vip_id(vip_id)


@pytest.fixture
def svc() -> tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo]:
    vips = InMemoryVipStore()
    profiles = FakeProfilesRepo()
    service = ProfileAdminService(
        profiles=profiles,
        vips=vips,
        owner_telegram_id=OWNER,
        clock=lambda: datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )
    return service, vips, profiles


@pytest.mark.asyncio
async def test_non_owner_raises_on_every_method(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, _ = svc
    await vips.add(555, display_name="Alice")
    with pytest.raises(OwnerAuthError):
        await service.show_profile(OTHER, 555)
    with pytest.raises(OwnerAuthError):
        await service.set_fact(OTHER, 555, "city", "BA")
    with pytest.raises(OwnerAuthError):
        await service.delete_fact(OTHER, 555, "city")
    with pytest.raises(OwnerAuthError):
        await service.add_note(OTHER, 555, "hello")
    with pytest.raises(OwnerAuthError):
        await service.delete_note(OTHER, 555, 1)


@pytest.mark.asyncio
async def test_unknown_tg_id_vip_not_found(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, _, _ = svc
    r = await service.show_profile(OWNER, 404)
    assert r.status == "vip_not_found"


@pytest.mark.asyncio
async def test_inactive_vip_not_found(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, _ = svc
    await vips.add(555, display_name="Alice")
    await vips.deactivate(555)
    r = await service.set_fact(OWNER, 555, "city", "BA")
    assert r.status == "vip_not_found"


@pytest.mark.asyncio
async def test_show_profile_empty_no_row(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, _ = svc
    await vips.add(555, display_name="Alice")
    r = await service.show_profile(OWNER, 555)
    assert r.status == "profile_empty"
    assert r.telegram_user_id == 555
    assert r.display_name == "Alice"


@pytest.mark.asyncio
async def test_show_profile_empty_hollow_row(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555)
    profiles.rows[rec.id] = empty_content()
    r = await service.show_profile(OWNER, 555)
    assert r.status == "profile_empty"
    assert is_hollow_content(profiles.rows[rec.id])


@pytest.mark.asyncio
async def test_show_profile_ok_with_content(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555, display_name="Alice")
    profiles.rows[rec.id] = {
        "facts": {"city": "BA"},
        "notes": [{"date": "2026-07-01", "text": "met"}],
    }
    r = await service.show_profile(OWNER, 555)
    assert r.status == "profile_ok"
    assert r.content is not None
    assert r.content["facts"]["city"] == "BA"
    assert len(r.content["notes"]) == 1


@pytest.mark.asyncio
async def test_set_fact_success(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555)
    r = await service.set_fact(OWNER, 555, "city", "BA")
    assert r.status == "fact_set"
    assert r.detail == "city"
    assert profiles.rows[rec.id]["facts"]["city"] == "BA"


@pytest.mark.asyncio
async def test_set_fact_overwrites_existing(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555)
    await service.set_fact(OWNER, 555, "city", "BA")
    r = await service.set_fact(OWNER, 555, "city", "MDZ")
    assert r.status == "fact_set"
    assert profiles.rows[rec.id]["facts"]["city"] == "MDZ"


@pytest.mark.asyncio
async def test_set_fact_invalid_empty_key(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, _ = svc
    await vips.add(555)
    r = await service.set_fact(OWNER, 555, "", "BA")
    assert r.status == "invalid"


@pytest.mark.asyncio
async def test_set_fact_invalid_empty_value(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, _ = svc
    await vips.add(555)
    r = await service.set_fact(OWNER, 555, "city", "   ")
    assert r.status == "invalid"


@pytest.mark.asyncio
async def test_set_fact_invalid_oversize_value(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    from diana.profile_content import MAX_FACT_VALUE_LEN

    service, vips, _ = svc
    await vips.add(555)
    r = await service.set_fact(OWNER, 555, "city", "x" * (MAX_FACT_VALUE_LEN + 1))
    assert r.status == "invalid"


@pytest.mark.asyncio
async def test_add_note_invalid_empty_text(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, _ = svc
    await vips.add(555)
    r = await service.add_note(OWNER, 555, "  ")
    assert r.status == "invalid"


@pytest.mark.asyncio
async def test_set_fact_integrity_error_maps_to_vip_not_found(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    """F3: FK / IntegrityError on write → vip_not_found (no unhandled bubble)."""
    IntegrityError = type("IntegrityError", (Exception,), {})

    service, vips, profiles = svc
    await vips.add(555)

    async def _boom(*_a, **_k):  # noqa: ANN001
        raise IntegrityError("fk violation")

    profiles.set_fact = _boom  # type: ignore[method-assign]
    r = await service.set_fact(OWNER, 555, "city", "BA")
    assert r.status == "vip_not_found"
    assert r.detail == "integrity"


@pytest.mark.asyncio
async def test_show_profile_whitespace_facts_is_empty(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555)
    profiles.rows[rec.id] = {"facts": {"city": "  "}, "notes": []}
    r = await service.show_profile(OWNER, 555)
    assert r.status == "profile_empty"


@pytest.mark.asyncio
async def test_delete_fact_missing_and_success(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555)
    await service.set_fact(OWNER, 555, "city", "BA")
    missing = await service.delete_fact(OWNER, 555, "nope")
    assert missing.status == "fact_missing"
    assert missing.detail == "nope"
    ok = await service.delete_fact(OWNER, 555, "city")
    assert ok.status == "fact_deleted"
    assert "city" not in profiles.rows[rec.id]["facts"]


@pytest.mark.asyncio
async def test_add_note_uses_clock_date(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555)
    r = await service.add_note(OWNER, 555, "met at event")
    assert r.status == "note_added"
    assert profiles.rows[rec.id]["notes"] == [
        {"date": "2026-07-27", "text": "met at event"}
    ]


@pytest.mark.asyncio
async def test_delete_note_1based_success_and_oob(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555)
    await service.add_note(OWNER, 555, "first")
    await service.add_note(OWNER, 555, "second")
    oob = await service.delete_note(OWNER, 555, 9)
    assert oob.status == "note_missing"
    ok = await service.delete_note(OWNER, 555, 1)
    assert ok.status == "note_deleted"
    assert len(profiles.rows[rec.id]["notes"]) == 1
    assert profiles.rows[rec.id]["notes"][0]["text"] == "second"


@pytest.mark.asyncio
async def test_module_has_no_aiogram_import() -> None:
    import ast
    from pathlib import Path

    import diana

    path = (
        Path(diana.__file__).resolve().parent
        / "application"
        / "profile_admin_service.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "aiogram" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("aiogram")
