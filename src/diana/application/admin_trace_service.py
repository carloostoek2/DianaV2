"""AdminTraceService — read-only trace query for owner DM.

Depends on ``TraceabilityReader`` protocol (no ORM types, no aiogram).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from diana.application.ports import TraceabilityReader

logger = logging.getLogger("diana.application")


@dataclass
class TurnSummary:
    """Summary of a turn for the /turnos list command."""

    turn_id: UUID
    chat_id: int
    vip_name: str | None = None
    message_preview: str = ""
    decision: str = ""
    status: str = ""
    created_at: datetime | None = None
    correction_applied: bool = False


@dataclass
class FullTrace:
    """Complete trace data for a single turn."""

    turn_id: UUID
    chat_id: int
    vip_id: UUID | None = None
    created_at: datetime | None = None
    comprehension: dict | None = None
    plan: dict | None = None
    retrieved: dict | None = None
    prompt_text: str | None = None
    generated_text: str | None = None
    evaluation: dict | None = None
    decision: dict | None = None
    delivery_result: dict | None = None
    timings: dict | None = None
    error: str | None = None
    status: str | None = None


_PREVIEW_LENGTH = 50


class AdminTraceService:
    """Read-only trace query service for the owner DM.

    Delegates storage retrieval to a ``TraceabilityReader`` implementation
    and maps raw dicts into typed DTOs (``TurnSummary``, ``FullTrace``).
    """

    def __init__(
        self,
        traces: TraceabilityReader,
        trace_ttl_days: int = 30,
    ) -> None:
        self._traces = traces
        self._ttl_days = trace_ttl_days

    async def get_recent_turns(
        self,
        limit: int = 10,
        offset: int = 0,
    ) -> list[TurnSummary]:
        """Return a list of recent turn summaries (newest first)."""
        rows = await self._traces.get_recent_turns(limit=limit, offset=offset)
        return [_row_to_summary(r) for r in rows]

    async def get_full_trace(self, turn_id: UUID) -> FullTrace | None:
        """Return the full trace for a turn, or None if not found."""
        row = await self._traces.get_full_trace(turn_id)
        if row is None:
            return None
        return _row_to_full_trace(row)

    async def count_recent(self) -> int:
        """Return the number of recent turns (within TTL)."""
        return await self._traces.count_recent()

    async def export_trace_json(self, turn_id: UUID) -> str:
        """Export full trace as a JSON string."""
        trace = await self.get_full_trace(turn_id)
        if trace is None:
            return json.dumps({"error": "trace not found", "turn_id": str(turn_id)})
        return json.dumps(
            _dataclass_to_dict(trace),
            default=str,
            indent=2,
            ensure_ascii=False,
        )


def _truncate(text: str | None, length: int = _PREVIEW_LENGTH) -> str:
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[:length] + "..."


def _row_to_summary(row: dict) -> TurnSummary:
    return TurnSummary(
        turn_id=row["turn_id"],
        chat_id=row["chat_id"],
        vip_name=row.get("display_name"),
        message_preview=_truncate(row.get("message_text")),
        decision=row.get("decision", ""),
        status=row.get("status", ""),
        created_at=row.get("created_at"),
        correction_applied=bool(row.get("correction_applied", False)),
    )


def _row_to_full_trace(row: dict) -> FullTrace:
    return FullTrace(
        turn_id=row["turn_id"],
        chat_id=row["chat_id"],
        vip_id=row.get("vip_id"),
        created_at=row.get("created_at"),
        comprehension=row.get("comprehension"),
        plan=row.get("plan"),
        retrieved=row.get("retrieved"),
        prompt_text=row.get("prompt_text"),
        generated_text=row.get("generated_text"),
        evaluation=row.get("evaluation"),
        decision=row.get("decision"),
        delivery_result=row.get("delivery_result"),
        timings=row.get("timings"),
        error=row.get("error"),
        status=row.get("status"),
    )


def _dataclass_to_dict(obj: Any) -> dict:
    """Recursively convert a dataclass to a plain dict."""
    if hasattr(obj, "__dataclass_fields__"):
        return {f: _dataclass_to_dict(getattr(obj, f)) for f in vars(obj) if getattr(obj, f) is not None}
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dataclass_to_dict(v) for v in obj]
    return obj


__all__ = [
    "AdminTraceService",
    "FullTrace",
    "TurnSummary",
]
