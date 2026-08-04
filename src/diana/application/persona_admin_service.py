"""Owner-gated persona catalog versioning (Item 1 domain; no wiring yet).

Writes (save / restore / list) are owner-only; the runtime read
``get_current_persona`` additionally honors the
``feature_persona_admin_enabled`` flag: when the flag is off it returns
``None`` so the pipeline keeps using the static ``persona_diana.json``
catalog (version 0 / seed).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from diana.application.admin_service import OwnerAuthError
from diana.application.ports import PersonaAdminStore, PersonaVersionRecord
from diana.cognitive.persona_catalog import validate_persona_catalog

logger = logging.getLogger("diana.application")


def _is_integrity_error(exc: BaseException) -> bool:
    """True for SQLAlchemy/asyncpg IntegrityError without importing sqlalchemy."""
    for cls in type(exc).__mro__:
        if cls.__name__ == "IntegrityError":
            return True
    return False


class PersonaAdminService:
    """Versioned persona catalog administration.

    ``save_persona`` validates the full catalog with the same pure validation
    as the static loader, persists it as a new version and immediately
    activates it (instant apply — the owner's edit becomes the active catalog).
    ``restore`` reactivates a previous version. ``get_current_persona`` is the
    runtime read used by the pipeline wiring (Item 2/3).

    Concurrency: the store's partial unique index guarantees at most one
    active row and the ``version`` unique index guarantees no duplicate
    version numbers. An ``IntegrityError`` from the version insert is
    surfaced as ``ValueError("persona_version_conflict")``; one from the
    activation swap as ``ValueError("persona_activation_conflict")``.

    Known accepted behavior: if activation fails after a successful insert
    (non-integrity failure, e.g. DB outage), the inserted row stays persisted
    inactive (a version gap is consumed). Owner-only usage makes this
    negligible; a retry simply creates the next version.
    """

    def __init__(
        self,
        *,
        payload_store: PersonaAdminStore,
        feature_persona_admin_enabled: bool,
        owner_telegram_id: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = payload_store
        self._enabled = bool(feature_persona_admin_enabled)
        self._owner_telegram_id = owner_telegram_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def _assert_owner(self, actor_id: int | None) -> None:
        if actor_id is None or actor_id != self._owner_telegram_id:
            raise OwnerAuthError(
                f"actor_id {actor_id!r} is not the configured owner"
            )

    async def save_persona(
        self, actor_id: int | None, payload: dict[str, Any]
    ) -> PersonaVersionRecord:
        """Validate the full catalog, persist it as a new active version."""
        self._assert_owner(actor_id)
        validated = validate_persona_catalog(dict(payload))
        versions = await self._store.list_versions()
        next_version = max((v.version for v in versions), default=0) + 1
        try:
            record = await self._store.insert_version(
                version=next_version,
                source="db",
                payload=validated,
                created_by=actor_id,
            )
        except Exception as exc:
            if _is_integrity_error(exc):
                logger.warning(
                    "persona_version_conflict",
                    extra={"actor_id": actor_id, "version": next_version},
                    exc_info=True,
                )
                raise ValueError("persona_version_conflict") from exc
            raise
        try:
            active = await self._store.activate_version(record.id, now=self._clock())
        except Exception as exc:
            if _is_integrity_error(exc):
                logger.warning(
                    "persona_activation_conflict",
                    extra={"actor_id": actor_id, "version": next_version},
                    exc_info=True,
                )
                raise ValueError("persona_activation_conflict") from exc
            raise
        logger.info(
            "persona_saved",
            extra={
                "actor_id": actor_id,
                "version": next_version,
                "persona_version_id": str(record.id),
            },
        )
        # ``active`` is the freshly activated record (the Protocol guarantees a
        # record for an existing id); the inserted record is returned as a
        # fallback only if the store returned None (defensive, unreachable).
        return active if active is not None else record

    async def restore(
        self, actor_id: int | None, persona_version_id: UUID
    ) -> PersonaVersionRecord | None:
        """Activate a previous version. Returns None when the id is unknown."""
        self._assert_owner(actor_id)
        try:
            restored = await self._store.activate_version(
                persona_version_id, now=self._clock()
            )
        except Exception as exc:
            if _is_integrity_error(exc):
                logger.warning(
                    "persona_activation_conflict",
                    extra={"actor_id": actor_id, "persona_version_id": str(persona_version_id)},
                    exc_info=True,
                )
                raise ValueError("persona_activation_conflict") from exc
            raise
        if restored is not None:
            logger.info(
                "persona_restored",
                extra={
                    "actor_id": actor_id,
                    "persona_version_id": str(persona_version_id),
                    "version": restored.version,
                },
            )
        return restored

    async def list_versions(self, actor_id: int | None) -> list[PersonaVersionRecord]:
        """All versions, newest first (owner-only)."""
        self._assert_owner(actor_id)
        return await self._store.list_versions()

    async def get_current_persona(self) -> dict[str, Any] | None:
        """Active payload when the feature flag is on; else ``None``."""
        if not self._enabled:
            return None
        record = await self._store.get_active()
        return record.payload if record is not None else None


__all__ = ["PersonaAdminService"]
