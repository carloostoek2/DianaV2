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

Concurrency: an epoch counter protects the cache from being clobbered by a
read that started before an ``invalidate``. If the DB read fails (outage), the
provider degrades to the static catalog instead of crashing the turn.
"""

from __future__ import annotations

import logging
from typing import Any

from diana.application.persona_admin_service import PersonaAdminService
from diana.cognitive.persona_catalog import get_persona_catalog

logger = logging.getLogger("diana.application")


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
        self._epoch = 0

    def invalidate(self) -> None:
        """Drop the cached catalog; the next ``get_catalog`` re-reads the service."""
        self._epoch += 1
        self._cached = None

    async def get_catalog(self) -> dict[str, Any] | None:
        """Full active catalog (DB version when flag on and active, else static).

        A read that started before an ``invalidate`` (same event loop, interleaved
        at the await) does not clobber the cache: its result is returned to the
        in-flight caller but only cached if no invalidation happened meanwhile.
        """
        if self._cached is not None:
            return self._cached
        epoch = self._epoch
        try:
            catalog = await self._service.get_current_persona()
        except Exception:
            logger.warning("persona_catalog_read_failed", exc_info=True)
            catalog = None
        if catalog is None:
            catalog = (
                self._static_catalog
                if self._static_catalog is not None
                else get_persona_catalog()
            )
        if epoch == self._epoch:
            self._cached = catalog
        return catalog


__all__ = ["PersonaCatalogProvider"]
