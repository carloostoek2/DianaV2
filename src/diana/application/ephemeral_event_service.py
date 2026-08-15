"""Owner-gated ephemeral events (eventos temporales) — domain layer.

Time-bounded context the owner injects so Diana responds accordingly for a
short window. Active window is ``[start_at, end_at)``: once ``now >= end_at``
the augmenter simply stops finding the event — no manual cleanup. Writes are
owner-only; reads (``find_active_at``) feed the per-turn knowledge augmenter.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Callable
from uuid import UUID

from diana.application.admin_service import OwnerAuthError
from diana.application.ports import EphemeralEventRecord, EphemeralEventStore

logger = logging.getLogger("diana.application")

# Tolerant relative-duration units (case-insensitive, optional accents).
_RELATIVE_UNITS: dict[str, str] = {
    "minuto": "minutos",
    "minutos": "minutos",
    "hora": "horas",
    "horas": "horas",
    "día": "dias",
    "días": "dias",
    "dia": "dias",
    "dias": "dias",
    "semana": "semanas",
    "semanas": "semanas",
}
_DELTA_PER_UNIT: dict[str, timedelta] = {
    "minutos": timedelta(minutes=1),
    "horas": timedelta(hours=1),
    "dias": timedelta(days=1),
    "semanas": timedelta(weeks=1),
}
_ABSOLUTE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?: (\d{1,2}):(\d{2}))?$")

_INVALID_DATETIME_MSG = (
    'No pude entender esa fecha. Usa una duración (ej. "2 horas", '
    '"3 días", "1 semana") o una fecha (ej. "2026-08-20" o '
    '"2026-08-20 18:00").'
)


def _local_tzinfo() -> tzinfo:
    """Naive datetimes are assumed to be in the server's local timezone."""
    return datetime.now().astimezone().tzinfo or UTC


class EphemeralEventService:
    """Owner-gated CRUD over time-bounded context events.

    ``parse_relative_or_absolute`` is tolerant on purpose: the Telegram wizard
    feeds free text (duration or absolute date) and retries the step on
    ``ValueError``.
    """

    def __init__(
        self,
        *,
        store: EphemeralEventStore,
        owner_telegram_id: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._owner_telegram_id = owner_telegram_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def _assert_owner(self, actor_id: int | None) -> None:
        if actor_id is None or actor_id != self._owner_telegram_id:
            raise OwnerAuthError(
                f"actor_id {actor_id!r} is not the configured owner"
            )

    async def create(
        self,
        actor_id: int | None,
        *,
        body: str,
        start_at: datetime,
        end_at: datetime,
    ) -> EphemeralEventRecord:
        self._assert_owner(actor_id)
        record = await self._store.create(
            body=body, start_at=start_at, end_at=end_at, created_by=actor_id,
        )
        logger.info(
            "ephemeral_event_created",
            extra={"actor_id": actor_id, "event_id": str(record.id)},
        )
        return record

    async def list_open(self, actor_id: int | None) -> list[EphemeralEventRecord]:
        """Events not yet terminated (active + paused + future) for the UI list."""
        self._assert_owner(actor_id)
        return await self._store.list_open(self._clock())

    async def get(
        self, actor_id: int | None, event_id: UUID
    ) -> EphemeralEventRecord | None:
        self._assert_owner(actor_id)
        return await self._store.get(event_id)

    async def set_paused(
        self, actor_id: int | None, event_id: UUID, paused: bool
    ) -> EphemeralEventRecord | None:
        self._assert_owner(actor_id)
        record = await self._store.set_paused(event_id, paused)
        if record is not None:
            logger.info(
                "ephemeral_event_paused" if paused else "ephemeral_event_resumed",
                extra={"actor_id": actor_id, "event_id": str(event_id)},
            )
        return record

    async def update(
        self,
        actor_id: int | None,
        event_id: UUID,
        *,
        body: str,
        start_at: datetime,
        end_at: datetime,
    ) -> EphemeralEventRecord | None:
        self._assert_owner(actor_id)
        record = await self._store.update(
            event_id, body=body, start_at=start_at, end_at=end_at
        )
        if record is not None:
            logger.info(
                "ephemeral_event_updated",
                extra={"actor_id": actor_id, "event_id": str(event_id)},
            )
        return record

    async def terminate(
        self, actor_id: int | None, event_id: UUID
    ) -> EphemeralEventRecord | None:
        self._assert_owner(actor_id)
        record = await self._store.terminate_now(event_id, self._clock())
        if record is not None:
            logger.info(
                "ephemeral_event_terminated",
                extra={"actor_id": actor_id, "event_id": str(event_id)},
            )
        return record

    async def delete(self, actor_id: int | None, event_id: UUID) -> bool:
        self._assert_owner(actor_id)
        deleted = await self._store.delete(event_id)
        if deleted:
            logger.info(
                "ephemeral_event_deleted",
                extra={"actor_id": actor_id, "event_id": str(event_id)},
            )
        return deleted

    def parse_relative_or_absolute(self, text: str, now: datetime) -> datetime:
        """Parse a duration or absolute date/time into an aware datetime.

        Supports relative ``<n> <unidad>`` (minuto(s)/hora(s)/día(s)/semana(s),
        case-insensitive, optional accents), ``"hoy"`` (end of today local),
        and absolute ``YYYY-MM-DD`` / ``YYYY-MM-DD HH:MM`` (naive → local).

        Raises ``ValueError`` with a clear Spanish message for the wizard retry.
        """
        cleaned = text.strip().lower()
        if cleaned == "hoy":
            return now.astimezone().replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

        parts = cleaned.split()
        if len(parts) == 2 and parts[0].isdigit():
            unit = _RELATIVE_UNITS.get(parts[1])
            if unit is not None:
                return now + int(parts[0]) * _DELTA_PER_UNIT[unit]

        match = _ABSOLUTE_RE.match(cleaned)
        if match is not None:
            year, month, day = (int(match.group(i)) for i in (1, 2, 3))
            hour = int(match.group(4) or 0)
            minute = int(match.group(5) or 0)
            try:
                naive = datetime(year, month, day, hour, minute)
            except ValueError:
                raise ValueError(_INVALID_DATETIME_MSG) from None
            return naive.replace(tzinfo=_local_tzinfo())

        raise ValueError(_INVALID_DATETIME_MSG)


__all__ = ["EphemeralEventService"]
