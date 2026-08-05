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
read that started before an ``invalidate``.

Failure semantics: if the DB read raises (outage) or the payload fails
``validate_persona_catalog`` (corrupt row), ``get_catalog`` returns ``None``
(consumers keep their boot-time static state) and the failure is NOT cached —
the next call retries the DB and picks up the active version once it is
available again.
"""

from __future__ import annotations

import logging
from typing import Any

from diana.application.persona_admin_service import PersonaAdminService
from diana.cognitive.persona_catalog import (
    get_persona_atencion_catalog,
    get_persona_catalog,
    validate_persona_catalog,
)

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
        self._cached: dict[str, dict[str, Any] | None] = {}
        self._epoch = 0

    def invalidate(self) -> None:
        """Drop the cached catalogs; the next ``get_catalog`` re-reads the service.

        Invalidates every channel (owner saves are rare; a single shared epoch
        counter keeps the logic simple and safe).
        """
        self._epoch += 1
        self._cached.clear()

    def _static_fallback(self, channel_type: str) -> dict[str, Any] | None:
        """Channel-scoped static catalog (boot-time persona files).

        Returns ``None`` (per the documented failure contract) when the file is
        missing/unreadable/invalid instead of raising out of ``get_catalog``.
        """
        try:
            if channel_type == "atencion":
                return get_persona_atencion_catalog()
            if self._static_catalog is not None:
                return self._static_catalog
            return get_persona_catalog()
        except (FileNotFoundError, OSError, ValueError):
            logger.warning(
                "persona_static_fallback_unavailable",
                extra={"channel_type": channel_type},
                exc_info=True,
            )
            return None

    async def get_catalog(
        self, channel_type: str = "vip"
    ) -> dict[str, Any] | None:
        """Full active catalog for a channel (DB version when flag on and active,
        else the channel's static persona).

        Returns ``None`` on DB failure or corrupt payload (never cached, so the
        next call retries). ``None`` from the service (flag off / no active
        version) falls back to the static catalog and IS cached — that is the
        steady-state 0-query path.

        A read that started before an ``invalidate`` (same event loop,
        interleaved at the await) does not clobber the cache: its result is
        returned to the in-flight caller but only cached if no invalidation
        happened meanwhile.
        """
        if channel_type not in ("vip", "atencion"):
            # S5: an unknown channel must never silently resolve the VIP persona.
            raise ValueError(f"unknown channel_type: {channel_type!r}")
        if channel_type in self._cached:
            return self._cached[channel_type]
        epoch = self._epoch
        try:
            catalog = await self._service.get_current_persona(
                channel_type=channel_type
            )
            if catalog is not None:
                # Defense-in-depth: the write path already validates; re-validating
                # on read keeps a corrupt DB row from crashing pipeline consumers.
                catalog = validate_persona_catalog(catalog)
        except Exception as exc:
            logger.warning(
                "persona_catalog_read_failed",
                extra={"error": type(exc).__name__},
                exc_info=True,
            )
            return None
        if catalog is None:
            catalog = self._static_fallback(channel_type)
        if epoch == self._epoch:
            self._cached[channel_type] = catalog
        return catalog


__all__ = ["PersonaCatalogProvider"]
