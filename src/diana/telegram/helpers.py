"""Shared presentation-layer helpers for Telegram handlers."""

from __future__ import annotations

from datetime import datetime, timezone


def _format_relative_time(dt: datetime | None) -> str:
    """Return a human-friendly relative time label in Spanish.

    Labels:
    - ``hace X minutos``  (< 60 minutes)
    - ``hace X horas``    (< 24 hours)
    - ``ayer a las HH:MM`` (< 48 hours)
    - ``hace X dias``     (< 7 days)
    - ``DD/MM/AAAA``      (7+ days, or future/missing)
    """
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = delta.total_seconds()
    if seconds < 0:
        return dt.strftime("%d/%m/%Y")
    minutes = int(seconds // 60)
    if minutes < 1:
        return "hace menos de un minuto"
    if minutes < 60:
        return f"hace {minutes} minuto{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    if hours < 24:
        return f"hace {hours} hora{'s' if hours != 1 else ''}"
    days = hours // 24
    if days == 1:
        return f"ayer a las {dt.strftime('%H:%M')}"
    if days < 7:
        return f"hace {days} días"
    return dt.strftime("%d/%m/%Y")
