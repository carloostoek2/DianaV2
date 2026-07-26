"""AdminTraceService — read-only trace query for owner DM.

Depends on ``TraceabilityReader`` protocol (no ORM types, no aiogram).
Presentation formatters return plain ``str`` / dataclasses only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from diana.application.ports import TraceabilityReader

logger = logging.getLogger("diana.application")

_PREVIEW_LENGTH = 50
_ORIGINAL_CAP = 200
_DRAFT_CAP = 80
_STEP_JSON_CAP = 1800
_SHORT_ID_LEN = 8
_DEFAULT_PAGE_LIMIT = 10
_TRUNCATION_SUFFIX = "\n... (truncated)"

_STEP_TIMING_KEY: dict[str, str] = {
    "analyst": "analyst_ms",
    "planner": "planner_ms",
    "memory_retriever": "memory_retriever_ms",
    "policy_retriever": "policy_retriever_ms",
    "examples_retriever": "examples_retriever_ms",
    "context_builder": "context_builder_ms",
    "generator": "generator_ms",
    "evaluator": "evaluator_ms",
    "decider": "decider_ms",
}


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


@dataclass
class TurnsPageView:
    """Rendered turns list page for handlers (plain data only)."""

    text: str
    turns_data: list[tuple[UUID, str]]
    page: int
    total_pages: int
    empty: bool


@dataclass
class TraceSummaryView:
    """Rendered trace summary for handlers (plain data only)."""

    text: str
    turn_id: UUID
    timings: dict | None


@dataclass
class StepDetailView:
    """Rendered step detail for handlers (plain data only)."""

    text: str
    turn_id: UUID


def format_relative_time(
    dt: datetime | None, *, now: datetime | None = None
) -> str:
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
    clock_now = now if now is not None else datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    if clock_now.tzinfo is None:
        clock_now = clock_now.replace(tzinfo=UTC)
    delta = clock_now - dt
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


def _truncate_json_block(value: Any) -> str:
    result = json.dumps(value, indent=2, default=str, ensure_ascii=False)
    if len(result) > _STEP_JSON_CAP:
        return result[:_STEP_JSON_CAP] + _TRUNCATION_SUFFIX
    return result


def _step_input_payload(step_name: str, trace: FullTrace) -> Any:
    step_input_map = {
        "analyst": trace.comprehension,
        "planner": trace.plan,
        "memory_retriever": trace.retrieved,
        "policy_retriever": trace.retrieved,
        "examples_retriever": trace.retrieved,
        "context_builder": trace.prompt_text,
        "generator": trace.prompt_text,
        "evaluator": trace.evaluation,
        "decider": trace.decision,
    }
    return step_input_map.get(step_name, {})


def _step_output_payload(step_name: str, trace: FullTrace) -> Any:
    step_output_map = {
        "analyst": trace.comprehension,
        "planner": trace.plan,
        "memory_retriever": trace.retrieved,
        "policy_retriever": trace.retrieved,
        "examples_retriever": trace.retrieved,
        "context_builder": trace.prompt_text,
        "generator": trace.generated_text,
        "evaluator": trace.evaluation,
        "decider": trace.decision,
    }
    return step_output_map.get(step_name, {})


def _format_step_input(step_name: str, trace: FullTrace) -> str:
    return _truncate_json_block(_step_input_payload(step_name, trace))


def _format_step_output(step_name: str, trace: FullTrace) -> str:
    return _truncate_json_block(_step_output_payload(step_name, trace))


class AdminTraceService:
    """Read-only trace query service for the owner DM.

    Delegates storage retrieval to a ``TraceabilityReader`` implementation
    and maps raw dicts into typed DTOs (``TurnSummary``, ``FullTrace``).
    Presentation formatters return plain strings / view dataclasses only.
    """

    def __init__(
        self,
        traces: TraceabilityReader,
        trace_ttl_days: int = 30,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._traces = traces
        self._ttl_days = trace_ttl_days
        self._clock = clock or (lambda: datetime.now(UTC))

    async def get_recent_turns(
        self,
        limit: int = 10,
        offset: int = 0,
        chat_id: int | None = None,
    ) -> list[TurnSummary]:
        """Return a list of recent turn summaries (newest first)."""
        rows = await self._traces.get_recent_turns(
            limit=limit, offset=offset, chat_id=chat_id
        )
        return [_row_to_summary(r) for r in rows]

    async def get_full_trace(self, turn_id: UUID) -> FullTrace | None:
        """Return the full trace for a turn, or None if not found."""
        row = await self._traces.get_full_trace(turn_id)
        if row is None:
            return None
        return _row_to_full_trace(row)

    async def count_recent(self, chat_id: int | None = None) -> int:
        """Return the number of recent turns (within TTL)."""
        return await self._traces.count_recent(chat_id=chat_id)

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

    def _relative(self, dt: datetime | None) -> str:
        return format_relative_time(dt, now=self._clock())

    def format_turns_list_text(
        self, turns: list[TurnSummary], *, page: int, total_pages: int
    ) -> str:
        """Format turns list body for /turnos and tp pagination."""
        lines: list[str] = [
            f"Recent turns (page {page + 1}/{total_pages}):",
            "",
        ]
        for i, t in enumerate(turns, 1):
            sid = str(t.turn_id)[:_SHORT_ID_LEN]
            name = t.vip_name or "Unknown"
            ts = self._relative(t.created_at)
            preview = t.message_preview
            lines.append(
                f'{i}. [{sid}] {name} (chat {t.chat_id}): "{preview}" '
                f"-> {t.decision} ({ts})"
            )
        return "\n".join(lines)

    def turns_keyboard_rows(
        self, turns: list[TurnSummary]
    ) -> list[tuple[UUID, str]]:
        """Return (turn_id, short_id) rows for trace_list_keyboard."""
        return [
            (t.turn_id, str(t.turn_id)[:_SHORT_ID_LEN]) for t in turns
        ]

    def format_trace_summary_text(self, trace: FullTrace) -> str:
        """Canonical trace summary (shared by /traza and vt)."""
        sid = str(trace.turn_id)[:_SHORT_ID_LEN]
        ts = self._relative(trace.created_at)
        original = (trace.prompt_text or "")[:_ORIGINAL_CAP]
        draft = (trace.generated_text or "")[:_DRAFT_CAP]
        decision_action = "N/A"
        if trace.decision:
            decision_action = trace.decision.get("action", "N/A")
        total_ms = 0
        if trace.timings:
            total_ms = int(
                sum(
                    v
                    for v in trace.timings.values()
                    if isinstance(v, (int, float))
                )
            )
        status = trace.status or "N/A"
        return "\n".join(
            [
                f"Trace {sid}",
                f"Date: {ts}",
                f"Status: {status}",
                f"Original intent: {original}",
                f'Draft: "{draft}..."',
                f"Decision: {decision_action}",
                f"Total time: {total_ms}ms",
            ]
        )

    def format_step_detail_text(self, trace: FullTrace, step: str) -> str:
        """Format step input/output detail for td callback."""
        timing_key = _STEP_TIMING_KEY.get(step, f"{step}_ms")
        ms = (trace.timings or {}).get(timing_key, "N/A")
        ms_label = f"{int(ms)}ms" if isinstance(ms, (int, float)) else "N/A"
        step_display = step.replace("_", " ").title()
        inp = _format_step_input(step, trace)
        out = _format_step_output(step, trace)
        return (
            f"Step: {step_display}\n"
            f"Duration: {ms_label}\n\n"
            f"Input:\n{inp}\n\n"
            f"Output:\n{out}"
        )

    async def render_turns_page(
        self,
        page: int = 0,
        *,
        limit: int = _DEFAULT_PAGE_LIMIT,
        chat_id: int | None = None,
    ) -> TurnsPageView:
        """Fetch and format a turns list page."""
        offset = page * limit
        turns = await self.get_recent_turns(
            limit=limit, offset=offset, chat_id=chat_id
        )
        total = await self.count_recent(chat_id=chat_id)
        total_pages = max(1, (total + limit - 1) // limit)
        if not turns:
            return TurnsPageView(
                text="",
                turns_data=[],
                page=page,
                total_pages=total_pages,
                empty=True,
            )
        return TurnsPageView(
            text=self.format_turns_list_text(
                turns, page=page, total_pages=total_pages
            ),
            turns_data=self.turns_keyboard_rows(turns),
            page=page,
            total_pages=total_pages,
            empty=False,
        )

    async def render_trace_summary(
        self, turn_id: UUID
    ) -> TraceSummaryView | None:
        """Fetch and format a trace summary, or None if not found."""
        trace = await self.get_full_trace(turn_id)
        if trace is None:
            return None
        return TraceSummaryView(
            text=self.format_trace_summary_text(trace),
            turn_id=trace.turn_id,
            timings=trace.timings,
        )

    async def render_step_detail(
        self, turn_id: UUID, step: str
    ) -> StepDetailView | None:
        """Fetch and format a step detail, or None if not found."""
        trace = await self.get_full_trace(turn_id)
        if trace is None:
            return None
        return StepDetailView(
            text=self.format_step_detail_text(trace, step),
            turn_id=trace.turn_id,
        )


def _truncate(text: str | None, length: int = _PREVIEW_LENGTH) -> str:
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[:length] + "..."


def _row_to_summary(row: dict) -> TurnSummary:
    decision_raw = row.get("decision")
    return TurnSummary(
        turn_id=row["turn_id"],
        chat_id=row["chat_id"],
        vip_name=row.get("display_name"),
        message_preview=_truncate(row.get("message_text")),
        decision=decision_raw.get("action", "")
        if isinstance(decision_raw, dict)
        else str(decision_raw or ""),
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
        return {f: _dataclass_to_dict(getattr(obj, f)) for f in vars(obj)}
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dataclass_to_dict(v) for v in obj]
    return obj


__all__ = [
    "AdminTraceService",
    "FullTrace",
    "StepDetailView",
    "TraceSummaryView",
    "TurnSummary",
    "TurnsPageView",
    "format_relative_time",
]
