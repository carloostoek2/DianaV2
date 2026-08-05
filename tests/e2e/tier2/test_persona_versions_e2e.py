"""E2E: persona_versions repo + PersonaAdminService against real PostgreSQL.

Covers the Item 1-2 core contract on a real DB: save → active, hot read via
get_current_persona (flag on), restore → single active swap, unknown restore
no-op, version numbering.
"""
import pytest

from diana.application.persona_admin_service import PersonaAdminService
from diana.application.persona_catalog_provider import PersonaCatalogProvider
from diana.cognitive.persona_catalog import get_persona_catalog
from diana.infrastructure.db.repositories.persona_versions import PersonaVersionRepo

OWNER_ID = 424242


def _valid_catalog() -> dict:
    catalog = get_persona_catalog()
    return {
        k: (list(v) if isinstance(v, list) else dict(v))
        for k, v in catalog.items()
    }


async def _global_max_version(session_factory) -> int:
    """Current max persona version across ALL channels (GLOBAL counter)."""
    from sqlalchemy import text

    async with session_factory() as sess:
        return (
            await sess.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) "
                    "FROM persona_versions"
                )
            )
        ).scalar_one()


@pytest.mark.db
@pytest.mark.asyncio
async def test_save_activate_and_current_persona_roundtrip(session_factory) -> None:
    repo = PersonaVersionRepo(session_factory)
    service = PersonaAdminService(
        payload_store=repo,
        feature_persona_admin_enabled=True,
        owner_telegram_id=OWNER_ID,
    )
    # The atencion seed consumed version 1 (max+1 at migration time), so the
    # first owner save takes the next global version — assert it via baseline.
    baseline = await _global_max_version(session_factory)
    record = await service.save_persona(OWNER_ID, _valid_catalog())
    assert record.version == baseline + 1
    assert record.source == "db"
    assert record.is_active  # save applies instantly

    current = await service.get_current_persona()
    assert current is not None
    assert current["voz_configurada"]["persona"] == _valid_catalog()["voz_configurada"]["persona"]


@pytest.mark.db
@pytest.mark.asyncio
async def test_restore_swaps_active_version(session_factory) -> None:
    repo = PersonaVersionRepo(session_factory)
    service = PersonaAdminService(
        payload_store=repo,
        feature_persona_admin_enabled=True,
        owner_telegram_id=OWNER_ID,
    )
    v1 = await service.save_persona(OWNER_ID, _valid_catalog())

    modified = _valid_catalog()
    modified["voz_configurada"]["reglas_estilo"].append("regla e2e v2")
    v2 = await service.save_persona(OWNER_ID, modified)
    assert v2.version == v1.version + 1  # global counter advances per save
    assert (await service.get_current_persona())["voz_configurada"]["reglas_estilo"][-1] == "regla e2e v2"

    restored = await service.restore(OWNER_ID, v1.id)
    assert restored is not None
    assert restored.version == v1.version
    current = await service.get_current_persona()
    assert "regla e2e v2" not in current["voz_configurada"]["reglas_estilo"]

    # one active row per channel: the VIP swap never touches the atencion seed
    # (which stays active on its own channel) — 2 active rows total.
    versions = await service.list_versions(OWNER_ID)
    assert len([v for v in versions if v.is_active]) == 2
    assert (
        len([v for v in versions if v.is_active and v.channel_type == "vip"]) == 1
    )
    assert (
        len([v for v in versions if v.is_active and v.channel_type == "atencion"])
        == 1
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_restore_unknown_id_is_noop(session_factory) -> None:
    from uuid import uuid4

    repo = PersonaVersionRepo(session_factory)
    service = PersonaAdminService(
        payload_store=repo,
        feature_persona_admin_enabled=True,
        owner_telegram_id=OWNER_ID,
    )
    v1 = await service.save_persona(OWNER_ID, _valid_catalog())
    assert await service.restore(OWNER_ID, uuid4()) is None
    current = await service.get_current_persona()
    assert current["voz_configurada"]["persona"] == v1.payload["voz_configurada"]["persona"]


@pytest.mark.db
@pytest.mark.asyncio
async def test_provider_caches_and_invalidates_after_save(session_factory) -> None:
    repo = PersonaVersionRepo(session_factory)
    service = PersonaAdminService(
        payload_store=repo,
        feature_persona_admin_enabled=True,
        owner_telegram_id=OWNER_ID,
    )
    provider = PersonaCatalogProvider(persona_admin_service=service)
    service.set_on_change(provider.invalidate)

    first = await provider.get_catalog()
    assert first is not None
    assert await provider.get_catalog() is first  # cached, 0 reads

    modified = _valid_catalog()
    modified["voz_configurada"]["reglas_estilo"].append("hot reload")
    await service.save_persona(OWNER_ID, modified)

    after = await provider.get_catalog()
    assert after is not None
    assert after is not first  # invalidated → re-read
    assert after["voz_configurada"]["reglas_estilo"][-1] == "hot reload"


@pytest.mark.db
@pytest.mark.asyncio
async def test_flag_off_get_current_persona_returns_none(session_factory) -> None:
    repo = PersonaVersionRepo(session_factory)
    service = PersonaAdminService(
        payload_store=repo,
        feature_persona_admin_enabled=False,
        owner_telegram_id=OWNER_ID,
    )
    await service.save_persona(OWNER_ID, _valid_catalog())
    assert await service.get_current_persona() is None
