"""Unit tests for PersonaCatalogProvider (cache, invalidation, fallback)."""

from __future__ import annotations

from typing import Any

import pytest

from diana.application.persona_catalog_provider import PersonaCatalogProvider
from diana.cognitive.persona_catalog import get_persona_catalog


def _catalog(marker: str) -> dict[str, Any]:
    return {
        "voz_configurada": {
            "persona": f"Diana {marker}",
            "reglas_estilo": [f"rule {marker}"],
        },
        "persona_facts": [{"id": "f1", "tema": ["x"], "hecho": marker}],
        "voice_patterns": [{"id": "p1", "tags": ["a"], "patron": "x", "uso": marker}],
        "policies": [{"id": "pol", "tema": ["t"], "regla": marker}],
        "schedule": {
            "timezone": "America/Mexico_City",
            "default_responses": [marker],
            "bloques": [],
        },
    }


class _FakeService:
    """Minimal PersonaAdminService double: returns a mutable current catalog."""

    def __init__(self, catalog: dict[str, Any] | None) -> None:
        self.catalog = catalog
        self.calls = 0

    async def get_current_persona(self) -> dict[str, Any] | None:
        self.calls += 1
        return self.catalog


@pytest.mark.asyncio
async def test_get_catalog_returns_service_catalog() -> None:
    service = _FakeService(_catalog("db"))
    provider = PersonaCatalogProvider(persona_admin_service=service)  # type: ignore[arg-type]
    catalog = await provider.get_catalog()
    assert catalog is not None
    assert catalog["voz_configurada"]["persona"] == "Diana db"


@pytest.mark.asyncio
async def test_cached_until_invalidate_zero_queries() -> None:
    service = _FakeService(_catalog("db"))
    provider = PersonaCatalogProvider(persona_admin_service=service)  # type: ignore[arg-type]
    first = await provider.get_catalog()
    second = await provider.get_catalog()
    assert first is second  # same object, no re-read
    assert service.calls == 1


@pytest.mark.asyncio
async def test_invalidate_force_reread() -> None:
    service = _FakeService(_catalog("v1"))
    provider = PersonaCatalogProvider(persona_admin_service=service)  # type: ignore[arg-type]
    await provider.get_catalog()
    service.catalog = _catalog("v2")
    provider.invalidate()
    catalog = await provider.get_catalog()
    assert catalog["voz_configurada"]["persona"] == "Diana v2"
    assert service.calls == 2


@pytest.mark.asyncio
async def test_fallback_to_static_catalog() -> None:
    service = _FakeService(None)
    provider = PersonaCatalogProvider(persona_admin_service=service)  # type: ignore[arg-type]
    catalog = await provider.get_catalog()
    # lru_cache returns the same object for the static catalog
    assert catalog is get_persona_catalog()


@pytest.mark.asyncio
async def test_custom_static_catalog_fallback() -> None:
    service = _FakeService(None)
    static = _catalog("static")
    provider = PersonaCatalogProvider(
        persona_admin_service=service,  # type: ignore[arg-type]
        static_catalog=static,
    )
    assert await provider.get_catalog() is static


def test_protocol_exported_in_cognitive_ports() -> None:
    import diana.cognitive.ports as ports

    assert hasattr(ports, "PersonaCatalogProvider")
    assert "PersonaCatalogProvider" in ports.__all__
    # runtime_checkable protocol with the async get_catalog contract
    assert "get_catalog" in getattr(ports.PersonaCatalogProvider, "__protocol_attrs__", set())


class _SlowService(_FakeService):
    """Service whose read can be interleaved with invalidate() at the await."""

    def __init__(self, catalog) -> None:
        super().__init__(catalog)
        self.release: asyncio.Event | None = None

    async def get_current_persona(self):
        self.calls += 1
        snapshot = self.catalog
        if self.release is not None:
            await self.release.wait()
        return snapshot


@pytest.mark.asyncio
async def test_invalidate_during_inflight_read_not_clobbered() -> None:
    """An in-flight read that started before invalidate() must not cache stale data."""
    import asyncio

    service = _SlowService(_catalog("old"))
    provider = PersonaCatalogProvider(persona_admin_service=service)  # type: ignore[arg-type]
    service.release = asyncio.Event()

    read_task = asyncio.create_task(provider.get_catalog())
    await asyncio.sleep(0)  # let the read start and hit the await
    service.catalog = _catalog("new")
    provider.invalidate()
    service.release.set()
    result = await read_task

    # The in-flight caller still gets its snapshot, but the cache was NOT
    # clobbered: the next read returns the new catalog without further awaits.
    assert result["voz_configurada"]["persona"] == "Diana old"
    next_catalog = await provider.get_catalog()
    assert next_catalog["voz_configurada"]["persona"] == "Diana new"
    assert service.calls == 2


@pytest.mark.asyncio
async def test_service_exception_returns_none_and_not_cached() -> None:
    """A DB outage returns None (consumers keep static state) and is NOT cached:
    the next call retries the DB and picks up the recovered catalog."""

    class _RecoveringService:
        def __init__(self) -> None:
            self.down = True

        async def get_current_persona(self):
            if self.down:
                raise RuntimeError("db down")
            return _catalog("recovered")

    service = _RecoveringService()
    provider = PersonaCatalogProvider(persona_admin_service=service)  # type: ignore[arg-type]
    assert await provider.get_catalog() is None
    assert await provider.get_catalog() is None  # still not cached: retries

    service.down = False
    catalog = await provider.get_catalog()
    assert catalog is not None
    assert catalog["voz_configurada"]["persona"] == "Diana recovered"


@pytest.mark.asyncio
async def test_corrupt_payload_returns_none_and_not_cached() -> None:
    """A corrupt DB payload (invalid catalog) must not reach consumers or cache."""

    class _CorruptService:
        def __init__(self) -> None:
            self.corrupt = True

        async def get_current_persona(self):
            if self.corrupt:
                return {"voz_configurada": {}}  # structurally invalid
            return _catalog("ok")

    service = _CorruptService()
    provider = PersonaCatalogProvider(persona_admin_service=service)  # type: ignore[arg-type]
    assert await provider.get_catalog() is None

    service.corrupt = False
    catalog = await provider.get_catalog()
    assert catalog is not None
    assert catalog["voz_configurada"]["persona"] == "Diana ok"
