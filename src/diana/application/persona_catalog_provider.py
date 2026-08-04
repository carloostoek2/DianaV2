"""Process-local cached view of the active persona catalog (single instance).

Implements the ``PersonaCatalogProvider`` protocol from ``diana.cognitive.ports``
(injected at the composition root). The cache holds the FULL validated catalog
dict; ``None`` means invalidated. ``get_catalog`` reads the active DB version
(flag-gated by ``PersonaAdminService.get_current_persona``) and falls back to
the lru-cached static catalog (``persona_diana.json``). Steady state: 0 reads —
repeated calls return the same cached object until ``invalidate`` is called
(after every owner save/restore via ``set_on_change``).

Process-local by design: ops are single-instance (``docs/OPS_SINGLE_INSTANCE.md``),
so invalidation within the process is sufficient.
"""

from __future__ import annotations

from typing import Any

from diana.application.persona_admin_service import PersonaAdminService
from diana.cognitive.persona_catalog import get_persona_catalog


class PersonaCatalogProvider:
    """Cached, invalidatable source of the effective persona catalog."""

    def __init__(
        self,
        persona_admin_service: PersonaAdminService,
        static_catalog: dict[str, Any] | None = None,
    ) -> None:
        self._service = persona_admin_service
        self._static_catalog = static_catalog  # None → use get_persona_catalog()
        self._cached: dict[str, Any] | None = None

    def invalidate(self) -> None:
        """Drop the cached catalog; the next ``get_catalog`` re-reads the service."""
        self._cached = None

    async def get_catalog(self) -> dict[str, Any] | None:
        """Full active catalog (DB version when flag on and active, else static)."""
        if self._cached is None:
            catalog = await self._service.get_current_persona()
            if catalog is None:
                catalog = (
                    self._static_catalog
                    if self._static_catalog is not None
                    else get_persona_catalog()
                )
            self._cached = catalog
        return self._cached


__all__ = ["PersonaCatalogProvider"]
