"""Compact owner draft keyboards (callback_data ≤ 64 bytes)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# action:{uuid} — approve / correct / escalate / doctrine_respond
_ACTION_APPROVE = "a"
_ACTION_CORRECT = "c"
_ACTION_ESCALATE = "e"
_ACTION_DOCTRINE_RESPOND = "dr"
_ACTION_DOCTRINE_RESOLVE = "dx"
_ACTION_DOCTRINE_ESCALATE = "de"
_ACTION_VIEW_TRACE = "vt"
_ACTION_TRACE_DETAIL = "td"
_ACTION_TRACE_PAGE = "tp"
_ACTION_TRACE_JSON = "tj"
# Metrics dashboard callbacks (mx:e export, mx:b back) — ≤64 bytes
_ACTION_METRICS_EXPORT = "mx:e"
_ACTION_METRICS_BACK = "mx:b"


def encode_callback(action: str, turn_id: UUID) -> str:
    """Build callback_data: a|c|e : <uuid>."""
    code = {
        "approve": _ACTION_APPROVE,
        "correct": _ACTION_CORRECT,
        "escalate": _ACTION_ESCALATE,
    }.get(action, action)
    data = f"{code}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_callback(data: str) -> tuple[str, UUID] | None:
    """Parse callback_data into (action_name, turn_id) or None."""
    if not data or ":" not in data:
        return None
    code, raw_id = data.split(":", 1)

    # Try doctrine callbacks first.
    if code == _ACTION_DOCTRINE_RESOLVE:
        try:
            return "resolve_with_draft", UUID(raw_id)
        except ValueError:
            return None
    if code == _ACTION_DOCTRINE_ESCALATE:
        try:
            return "escalate_doctrine", UUID(raw_id)
        except ValueError:
            return None
    if code == _ACTION_DOCTRINE_RESPOND:
        try:
            return "respond_doctrine", UUID(raw_id)
        except ValueError:
            return None

    action = {
        _ACTION_APPROVE: "approve",
        _ACTION_CORRECT: "correct",
        _ACTION_ESCALATE: "escalate",
    }.get(code)
    if action is None:
        return None
    try:
        return action, UUID(raw_id)
    except ValueError:
        return None


def encode_doctrine_callback(turn_id: UUID) -> str:
    """Build callback_data for doctrine respond button: dr:<uuid>."""
    data = f"{_ACTION_DOCTRINE_RESPOND}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_doctrine_callback(data: str, prefix: str | None = None) -> UUID | None:
    """Extract UUID from doctrine callback data (dr:|dx:|de:<uuid>).

    Args:
        data: The callback data string.
        prefix: If provided, only match this prefix (e.g. ``"dr"``).
                When ``None`` (default), any prefix is accepted.
    """
    if not data or ":" not in data:
        return None
    code, raw_id = data.split(":", 1)
    if prefix is not None and code != prefix:
        return None
    try:
        return UUID(raw_id)
    except ValueError:
        return None


def draft_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """Approve / Correct / Escalate inline keyboard for owner DM."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=encode_callback("approve", turn_id),
                ),
                InlineKeyboardButton(
                    text="✏️ Correct",
                    callback_data=encode_callback("correct", turn_id),
                ),
                InlineKeyboardButton(
                    text="⚠️ Escalate",
                    callback_data=encode_callback("escalate", turn_id),
                ),
            ]
        ]
    )


def encode_doctrine_resolve_callback(turn_id: UUID) -> str:
    """Build callback_data for doctrine resolve-with-draft button: dx:<uuid>."""
    data = f"{_ACTION_DOCTRINE_RESOLVE}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_doctrine_escalate_callback(turn_id: UUID) -> str:
    """Build callback_data for doctrine escalate button: de:<uuid>."""
    data = f"{_ACTION_DOCTRINE_ESCALATE}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def doctrine_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """Reply markup for gray zone doctrine queries (three actions).

    - Respond: owner writes free-text doctrine
    - Use draft: auto-resolve with the existing draft
    - Escalate: discard query, escalate turn
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Respond to query",
                    callback_data=encode_doctrine_callback(turn_id),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Use draft as-is",
                    callback_data=encode_doctrine_resolve_callback(turn_id),
                ),
                InlineKeyboardButton(
                    text="Escalate",
                    callback_data=encode_doctrine_escalate_callback(turn_id),
                ),
            ],
        ]
    )


# ---- Trace callback helpers ----


@dataclass
class TraceCallbackData:
    """Parsed trace callback data."""

    action: str
    turn_id: UUID | None = None
    step: str | None = None
    page: int | None = None

_STEP_DISPLAY_NAMES: dict[str, str] = {
    "analyst": "Analyst",
    "planner": "Planner",
    "memory_retriever": "MemoryRetriever",
    "policy_retriever": "PolicyRetriever",
    "examples_retriever": "ExamplesRetriever",
    "context_builder": "ContextBuilder",
    "generator": "Generator",
    "evaluator": "Evaluator",
    "decider": "Decider",
}


def encode_trace_view(turn_id: UUID) -> str:
    """Build callback_data for viewing a trace: vt:<uuid>."""
    data = f"{_ACTION_VIEW_TRACE}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_trace_detail(turn_id: UUID, step_name: str) -> str:
    """Build callback_data for a step detail: td:<uuid>:<step>."""
    data = f"{_ACTION_TRACE_DETAIL}:{turn_id}:{step_name}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_trace_page(page: int) -> str:
    """Build callback_data for pagination: tp:<page>."""
    data = f"{_ACTION_TRACE_PAGE}:{page}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_trace_json(turn_id: UUID) -> str:
    """Build callback_data for JSON export: tj:<uuid>."""
    data = f"{_ACTION_TRACE_JSON}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_trace_callback(data: str) -> TraceCallbackData | None:
    """Parse trace callback data into a typed dataclass.

    Returns ``None`` when the prefix is not a trace action.
    Otherwise returns a ``TraceCallbackData`` with fields: action, turn_id, step, page.
    """
    if not data or ":" not in data:
        return None
    parts = data.split(":", 2)
    code = parts[0]

    actions = {_ACTION_VIEW_TRACE, _ACTION_TRACE_DETAIL, _ACTION_TRACE_PAGE, _ACTION_TRACE_JSON}
    if code not in actions:
        return None

    if code == _ACTION_TRACE_PAGE:
        try:
            return TraceCallbackData(action=code, page=int(parts[1]))
        except (ValueError, IndexError):
            return None

    if code == _ACTION_TRACE_DETAIL:
        try:
            return TraceCallbackData(
                action=code,
                turn_id=UUID(parts[1]),
                step=parts[2] if len(parts) > 2 else None,
            )
        except (ValueError, IndexError):
            return None

    # vt or tj
    try:
        return TraceCallbackData(action=code, turn_id=UUID(parts[1]))
    except (ValueError, IndexError):
        return None


def trace_list_keyboard(
    turns: list[tuple[UUID, str]], page: int, total_pages: int,
) -> InlineKeyboardMarkup:
    """Keyboard for the /turnos list with turn buttons + pagination."""
    buttons: list[list[InlineKeyboardButton]] = []

    # One button per turn.
    for turn_id, short_id in turns:
        buttons.append([
            InlineKeyboardButton(
                text=f"Trace {short_id}",
                callback_data=encode_trace_view(turn_id),
            ),
        ])

    # Pagination row.
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="Previous",
                callback_data=encode_trace_page(page - 1),
            )
        )
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton(
                text="Next",
                callback_data=encode_trace_page(page + 1),
            )
        )
    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def trace_detail_keyboard(
    turn_id: UUID,
    timings: dict[str, float] | None = None,
) -> InlineKeyboardMarkup:
    """Keyboard with per-step buttons and export/back actions."""
    timings = timings or {}
    buttons: list[list[InlineKeyboardButton]] = []

    step_order = [
        "analyst",
        "planner",
        "memory_retriever",
        "policy_retriever",
        "examples_retriever",
        "context_builder",
        "generator",
        "evaluator",
        "decider",
    ]

    for step_key in step_order:
        display = _STEP_DISPLAY_NAMES.get(step_key, step_key)
        ms = timings.get(f"{step_key}_ms")
        label = f"{display}" + (f" ({int(ms)}ms)" if ms is not None else "")
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=encode_trace_detail(turn_id, step_key),
            ),
        ])

    # Bottom row: export JSON + back to turns.
    buttons.append([
        InlineKeyboardButton(
            text="Export JSON",
            callback_data=encode_trace_json(turn_id),
        ),
        InlineKeyboardButton(
            text="Back to turns",
            callback_data=encode_trace_page(0),
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def step_detail_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """Keyboard with a single "Back to trace" button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Back to trace",
                    callback_data=encode_trace_view(turn_id),
                ),
            ],
        ]
    )


# ---- Patch draft_keyboard with Trace button ----
_draft_base = draft_keyboard


def draft_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """Approve / Correct / Escalate / Trace inline keyboard for owner DM."""
    base = _draft_base(turn_id)
    trace_row = [
        InlineKeyboardButton(
            text="Trace",
            callback_data=f"{_ACTION_VIEW_TRACE}:{turn_id}",
        ),
    ]
    base.inline_keyboard.append(trace_row)
    return base


def encode_metrics_export() -> str:
    """callback_data for metrics JSON export (≤64 bytes)."""
    data = _ACTION_METRICS_EXPORT
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_metrics_back() -> str:
    """callback_data for metrics back-to-menu (≤64 bytes)."""
    data = _ACTION_METRICS_BACK
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_metrics_callback(data: str) -> str | None:
    """Parse metrics callback into action name: export | back | None."""
    if data == _ACTION_METRICS_EXPORT:
        return "export"
    if data == _ACTION_METRICS_BACK:
        return "back"
    return None


def metrics_keyboard() -> InlineKeyboardMarkup:
    """[Exportar datos] [Volver] under the weekly metrics summary."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Exportar datos",
                    callback_data=encode_metrics_export(),
                ),
                InlineKeyboardButton(
                    text="🔙 Volver",
                    callback_data=encode_metrics_back(),
                ),
            ],
        ]
    )


__all__ = [
    "TraceCallbackData",
    "doctrine_keyboard",
    "draft_keyboard",
    "encode_callback",
    "encode_doctrine_callback",
    "encode_doctrine_resolve_callback",
    "encode_doctrine_escalate_callback",
    "encode_metrics_back",
    "encode_metrics_export",
    "encode_trace_view",
    "encode_trace_detail",
    "encode_trace_page",
    "encode_trace_json",
    "metrics_keyboard",
    "parse_callback",
    "parse_doctrine_callback",
    "parse_metrics_callback",
    "parse_trace_callback",
    "step_detail_keyboard",
    "trace_detail_keyboard",
    "trace_list_keyboard",
]
