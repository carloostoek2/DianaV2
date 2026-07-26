"""Shared presentation-layer helpers for Telegram handlers."""

from __future__ import annotations

from datetime import datetime

from diana.application.admin_trace_service import format_relative_time


def _format_relative_time(dt: datetime | None) -> str:
    """Return a human-friendly relative time label in Spanish.

    Delegates to application ``format_relative_time`` (single source of truth).
    """
    return format_relative_time(dt)
