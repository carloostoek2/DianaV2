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

    async def delete_by_vip_id(self, vip_id: UUID) -> bool:
        if vip_id not in self.rows:
            return False
        del self.rows[vip_id]
        return True


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


# --- purge_profile_for_telegram_user (item2 vip-crud) ---


@pytest.mark.asyncio
async def test_purge_non_owner_raises(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, _ = svc
    await vips.add(555)
    with pytest.raises(OwnerAuthError):
        await service.purge_profile_for_telegram_user(OTHER, 555)


@pytest.mark.asyncio
async def test_purge_unknown_tg_id_vip_not_found(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, _, _ = svc
    r = await service.purge_profile_for_telegram_user(OWNER, 404)
    assert r.status == "vip_not_found"
    assert r.telegram_user_id == 404


@pytest.mark.asyncio
async def test_purge_active_vip_with_profile_row(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    rec = await vips.add(555, display_name="Alice")
    profiles.rows[rec.id] = {"facts": {"city": "BA"}, "notes": []}
    r = await service.purge_profile_for_telegram_user(OWNER, 555)
    assert r.status == "profile_purged"
    assert rec.id not in profiles.rows
    assert r.telegram_user_id == 555
    assert r.display_name == "Alice"


@pytest.mark.asyncio
async def test_purge_after_deactivate_still_works(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    """Purge must resolve inactive VIP (post /remove_vip deactivate)."""
    service, vips, profiles = svc
    rec = await vips.add(555, display_name="Alice")
    profiles.rows[rec.id] = {"facts": {"city": "BA"}, "notes": []}
    await vips.deactivate(555)

    r = await service.purge_profile_for_telegram_user(OWNER, 555)
    assert r.status == "profile_purged"
    assert rec.id not in profiles.rows


@pytest.mark.asyncio
async def test_purge_no_profile_row_profile_absent(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    service, vips, profiles = svc
    await vips.add(555, display_name="Alice")
    r = await service.purge_profile_for_telegram_user(OWNER, 555)
    assert r.status == "profile_absent"
    assert profiles.rows == {}


# --- F5 Pool 4 (F5-06): semantic memory section in the ficha ---


class FakeMemoriesReader:
    """MemoryFactsReader double: list_by_vip returns the wired rows."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])
        self.calls: list[UUID] = []

    async def list_by_vip(self, vip_id: UUID) -> list[dict]:
        self.calls.append(vip_id)
        return [dict(r) for r in self.rows]


@pytest.mark.asyncio
async def test_show_profile_includes_memory_when_wired(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    """F5-06: with a memories reader wired, show_profile includes the memory
    rows in BOTH result paths (profile_ok)."""
    service, vips, profiles = svc
    rec = await vips.add(555, display_name="Alice")
    profiles.rows[rec.id] = {"facts": {"city": "BA"}, "notes": []}
    rows = [
        {
            "category": "preferencias",
            "status": "auto",
            "content": {"texto": "Le gusta viajar"},
        },
        {
            "category": "sensible",
            "status": "pending_owner",
            "content": {"texto": "Mencionó su salud"},
        },
    ]
    memories = FakeMemoriesReader(rows)
    wired = ProfileAdminService(
        profiles=profiles,
        vips=vips,
        owner_telegram_id=OWNER,
        memories=memories,
        clock=lambda: datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )

    r = await wired.show_profile(OWNER, 555)

    assert r.status == "profile_ok"
    assert r.memory == rows
    assert memories.calls == [rec.id]


@pytest.mark.asyncio
async def test_show_profile_memory_none_when_unwired(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    """F5-06: without a memories reader (flag OFF) the result carries
    memory=None and the empty-card early return stays intact."""
    service, vips, _ = svc
    await vips.add(555, display_name="Alice")

    r = await service.show_profile(OWNER, 555)

    assert r.status == "profile_empty"
    assert r.memory is None


# --- Evo-Agente Fase 5 (EA-06): 🔐 Confianza section of the ficha -----------


class FakeTrustBudget:
    """TrustBudget double: list_for_ficha returns the wired rows."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])
        self.calls: list[UUID] = []

    async def list_for_ficha(self, vip_id: UUID) -> list[dict]:
        self.calls.append(vip_id)
        return [dict(r) for r in self.rows]


@pytest.mark.asyncio
async def test_show_profile_includes_trust_when_wired(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    """EA-06: with a trust service wired, show_profile carries the trust rows
    in BOTH result paths (profile_empty and profile_ok)."""
    service, vips, profiles = svc
    rec = await vips.add(555, display_name="Alice")
    rows = [
        {
            "category": "fatico",
            "trust_score": 0.42,
            "autonomous_count": 3,
            "correction_count": 1,
            "last_correction_at": "2026-08-05T10:00:00+00:00",
            "trend": "down",
        }
    ]
    trust = FakeTrustBudget(rows)
    wired = ProfileAdminService(
        profiles=profiles,
        vips=vips,
        owner_telegram_id=OWNER,
        trust_budget=trust,
        clock=lambda: datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
    )

    # profile_empty path.
    r_empty = await wired.show_profile(OWNER, 555)
    assert r_empty.status == "profile_empty"
    assert r_empty.trust_budget == rows
    assert trust.calls == [rec.id]

    # profile_ok path.
    profiles.rows[rec.id] = {"facts": {"city": "BA"}, "notes": []}
    r_ok = await wired.show_profile(OWNER, 555)
    assert r_ok.status == "profile_ok"
    assert r_ok.trust_budget == rows


@pytest.mark.asyncio
async def test_show_profile_trust_none_when_unwired(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    """EA-06: without a trust service (flag OFF) → trust_budget=None
    (byte-identical — existing ficha untouched)."""
    service, vips, _ = svc
    await vips.add(555, display_name="Alice")

    r = await service.show_profile(OWNER, 555)

    assert r.status == "profile_empty"
    assert r.trust_budget is None


@pytest.mark.asyncio
async def test_show_profile_empty_trust_rows_normalized_to_none(
    svc: tuple[ProfileAdminService, InMemoryVipStore, FakeProfilesRepo],
) -> None:
    """EA-06: an empty list (VIP without trust history) becomes None so the
    ficha never renders an orphan 🔐 header."""
    service, vips, _ = svc
    rec = await vips.add(555, display_name="Alice")
    wired = ProfileAdminService(
        profiles=service._profiles,  # noqa: SLF001
        vips=vips,
        owner_telegram_id=OWNER,
        trust_budget=FakeTrustBudget([]),
    )

    r = await wired.show_profile(OWNER, 555)

    assert r.status == "profile_empty"
    assert r.trust_budget is None
