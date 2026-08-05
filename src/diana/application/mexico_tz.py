"""Civil-date helpers for the America/Mexico_City timezone (F4-02).

Mirror of ``cognitive/retrievers/context.py`` (_to_cdmx). Deliberately NOT
imported from cognitive: the layering rules forbid an application-layer module
from depending on cognitive, so the conversion is duplicated here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

CDMX_TZ = ZoneInfo("America/Mexico_City")


def cdmx_local_date(value: datetime) -> date:
    """Civil date in America/Mexico_City; naive values treated as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(CDMX_TZ).date()


def cdmx_local_midnight(value: datetime) -> datetime:
    """UTC instant of the start (00:00) of the CDMX civil day for ``value``.

    Naive values are treated as UTC. Useful to anchor "today" windows on the
    CDMX calendar day instead of a rolling 24h span.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    local = value.astimezone(CDMX_TZ)
    midnight_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local.astimezone(UTC)


__all__ = ["CDMX_TZ", "cdmx_local_date", "cdmx_local_midnight"]
