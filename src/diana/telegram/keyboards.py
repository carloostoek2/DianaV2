"""Compact owner draft keyboards (callback_data ≤ 64 bytes)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from diana.application.ports import EphemeralEventRecord

# action:{uuid} — approve / correct / escalate / doctrine_respond
_ACTION_APPROVE = "a"
_ACTION_CORRECT = "c"
_ACTION_ESCALATE = "e"
_ACTION_REGEN = "rg"
_ACTION_PREV = "pv"
_ACTION_NEXT = "nx"
_ACTION_DOCTRINE_RESPOND = "dr"
_ACTION_DOCTRINE_RESOLVE = "dx"
_ACTION_DOCTRINE_ESCALATE = "de"
_ACTION_DOCTRINE_SCOPE = "ds"
_ACTION_VIEW_TRACE = "vt"
_ACTION_TRACE_DETAIL = "td"
_ACTION_TRACE_PAGE = "tp"
_ACTION_TRACE_JSON = "tj"
# Trace entered from the owner draft — keeps "back to draft" navigation.
_ACTION_VIEW_TRACE_FROM_DRAFT = "vtd"
_ACTION_TRACE_DETAIL_FROM_DRAFT = "tdd"
_ACTION_TRACE_BACK_TO_DRAFT = "tb"
# Add note callback (an:<chat_id>) — ≤64 bytes
_ACTION_ADD_NOTE = "an"
# Metrics dashboard callbacks (mx:e export, mx:b back) — ≤64 bytes
_ACTION_METRICS_EXPORT = "mx:e"
_ACTION_METRICS_BACK = "mx:b"
# Staging queue (sp: promote, sd: discard) — ≤64 bytes
_ACTION_STAGING_PROMOTE = "sp"
_ACTION_STAGING_DISCARD = "sd"
# Memory approval (mp: approve, md: discard) — F5 Pool 4, ≤64 bytes.
# NOTE: the menu prefix is the literal "m:" (char 1 = ':'), so "mp:"/"md:"
# never collide with the menu lambda (A1).
_ACTION_MEMORY_APPROVE = "mp"
_ACTION_MEMORY_DISCARD = "md"
# Hierarchical owner menu (m:<category> or m:<category>:<action>) — ≤64 bytes
_ACTION_MENU = "m"
# Quality feedback on VIP drafts (gd/rp tap; gdc/rpc confirm) — ≤64 bytes
_ACTION_GOLD = "gd"
_ACTION_REPRIMAND = "rp"
_ACTION_GOLD_CONFIRM = "gdc"
_ACTION_REPRIMAND_CONFIRM = "rpc"

_GOLD_SCOPE = {"g": "global", "v": "vip"}
_REPRIMAND_MODE = {"pol": "policy", "ex": "counter_example"}


def encode_callback(action: str, turn_id: UUID) -> str:
    """Build callback_data: a|c|e|rg|pv|nx : <uuid>."""
    code = {
        "approve": _ACTION_APPROVE,
        "correct": _ACTION_CORRECT,
        "escalate": _ACTION_ESCALATE,
        "regen": _ACTION_REGEN,
        "prev": _ACTION_PREV,
        "next": _ACTION_NEXT,
        "gold": _ACTION_GOLD,
        "reprimand": _ACTION_REPRIMAND,
    }.get(action, action)
    data = f"{code}:{turn_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_add_note(chat_id: int) -> str:
    """Build callback_data for add-note button: an:<chat_id>."""
    data = f"{_ACTION_ADD_NOTE}:{chat_id}"
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
        _ACTION_REGEN: "regen",
        _ACTION_PREV: "prev",
        _ACTION_NEXT: "next",
        _ACTION_GOLD: "gold",
        _ACTION_REPRIMAND: "reprimand",
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


def draft_keyboard(
    turn_id: UUID, *, show_quality_feedback: bool = False
) -> InlineKeyboardMarkup:
    """Aprobar / Corregir / Escalar inline keyboard for owner DM."""
    rows = [
        [
            InlineKeyboardButton(
                text="✅ Aprobar",
                callback_data=encode_callback("approve", turn_id),
            ),
            InlineKeyboardButton(
                text="✏️ Corregir",
                callback_data=encode_callback("correct", turn_id),
            ),
            InlineKeyboardButton(
                text="⚠️ Escalar",
                callback_data=encode_callback("escalate", turn_id),
            ),
        ]
    ]
    if show_quality_feedback:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Destacar",
                    callback_data=encode_callback("gold", turn_id),
                ),
                InlineKeyboardButton(
                    text="Reprender",
                    callback_data=encode_callback("reprimand", turn_id),
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def encode_gold_confirm(turn_id: UUID, scope: str) -> str:
    """Build callback_data: gdc:<uuid>:g|v|x."""
    if scope not in {"g", "v", "x"}:
        raise ValueError(f"invalid gold scope: {scope!r}")
    data = f"{_ACTION_GOLD_CONFIRM}:{turn_id}:{scope}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_gold_confirm(data: str) -> tuple[UUID, str] | str | None:
    """Parse gdc:<uuid>:g|v|x → (tid, global|vip) or 'cancel'."""
    if not data or not data.startswith(f"{_ACTION_GOLD_CONFIRM}:"):
        return None
    rest = data.split(":", 1)[1]
    if ":" not in rest:
        return None
    raw_id, scope = rest.rsplit(":", 1)
    try:
        turn_id = UUID(raw_id)
    except ValueError:
        return None
    if scope == "x":
        return "cancel"
    mapped = _GOLD_SCOPE.get(scope)
    if mapped is None:
        return None
    return turn_id, mapped


def encode_reprimand_confirm(turn_id: UUID, mode: str, scope: str) -> str:
    """Build callback_data: rpc:<uuid>:pol|ex:g|v."""
    if mode not in _REPRIMAND_MODE or scope not in _GOLD_SCOPE:
        raise ValueError(f"invalid reprimand confirm: {mode!r}/{scope!r}")
    data = f"{_ACTION_REPRIMAND_CONFIRM}:{turn_id}:{mode}:{scope}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_reprimand_confirm(data: str) -> tuple[UUID, str, str] | None:
    """Parse rpc:<uuid>:pol|ex:g|v → (tid, policy|counter_example, global|vip)."""
    if not data or ":" not in data:
        return None
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != _ACTION_REPRIMAND_CONFIRM:
        return None
    try:
        turn_id = UUID(parts[1])
    except ValueError:
        return None
    mode = _REPRIMAND_MODE.get(parts[2])
    scope = _GOLD_SCOPE.get(parts[3])
    if mode is None or scope is None:
        return None
    return turn_id, mode, scope


def gold_scope_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """General / Este VIP + Volver for Destacar confirm."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌍 General",
                    callback_data=encode_gold_confirm(turn_id, "g"),
                ),
                InlineKeyboardButton(
                    text="👤 Este VIP",
                    callback_data=encode_gold_confirm(turn_id, "v"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Volver",
                    callback_data=encode_gold_confirm(turn_id, "x"),
                ),
            ],
        ]
    )


def reprimand_combo_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """Promote-only lesson combo after reprimand text is already delivered."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Regla dura · General",
                    callback_data=encode_reprimand_confirm(turn_id, "pol", "g"),
                ),
                InlineKeyboardButton(
                    text="Regla dura · Este VIP",
                    callback_data=encode_reprimand_confirm(turn_id, "pol", "v"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="No repetir · General",
                    callback_data=encode_reprimand_confirm(turn_id, "ex", "g"),
                ),
                InlineKeyboardButton(
                    text="No repetir · Este VIP",
                    callback_data=encode_reprimand_confirm(turn_id, "ex", "v"),
                ),
            ],
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


def encode_doctrine_scope(turn_id: UUID, scope: str) -> str:
    """Build callback_data for doctrine scope choice: ds:<uuid>:<vip|all|cancel>."""
    data = f"{_ACTION_DOCTRINE_SCOPE}:{turn_id}:{scope}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_doctrine_scope(data: str) -> tuple[UUID, str] | None:
    """Parse ds:<uuid>:<scope> → (turn_id, scope); None on malformed data."""
    if not data or not data.startswith(f"{_ACTION_DOCTRINE_SCOPE}:"):
        return None
    rest = data[len(_ACTION_DOCTRINE_SCOPE) + 1 :]
    parts = rest.split(":")
    if len(parts) != 2:
        return None
    try:
        turn_id = UUID(parts[0])
    except ValueError:
        return None
    scope = parts[1]
    if scope not in ("vip", "all", "cancel"):
        return None
    return (turn_id, scope)


def doctrine_scope_keyboard(turn_id: UUID) -> InlineKeyboardMarkup:
    """Scope choice for a new doctrine rule (GAP-11): this VIP or everyone.

    Also offers a cancel that discards the pending doctrine response.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔒 Solo este VIP",
                    callback_data=encode_doctrine_scope(turn_id, "vip"),
                ),
                InlineKeyboardButton(
                    text="🌍 A todos",
                    callback_data=encode_doctrine_scope(turn_id, "all"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Cancelar",
                    callback_data=encode_doctrine_scope(turn_id, "cancel"),
                ),
            ],
        ]
    )


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
                    text="📝 Responder consulta",
                    callback_data=encode_doctrine_callback(turn_id),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Usar borrador",
                    callback_data=encode_doctrine_resolve_callback(turn_id),
                ),
                InlineKeyboardButton(
                    text="⚠️ Escalar",
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


def encode_trace_view(
    turn_id: UUID, from_draft: bool = False, page: int | None = None
) -> str:
    """Build callback_data for viewing a trace: vt:<uuid> (vtd when from draft).

    ``page`` (optional) is appended as ``:N`` so "Volver a turnos" can restore
    the exact list page the owner was on (A10), instead of resetting to page 0.
    """
    code = _ACTION_VIEW_TRACE_FROM_DRAFT if from_draft else _ACTION_VIEW_TRACE
    data = f"{code}:{turn_id}"
    if page:
        data = f"{data}:{page}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_trace_detail(
    turn_id: UUID, step_name: str, from_draft: bool = False
) -> str:
    """Build callback_data for a step detail: td:<uuid>:<step> (tdd when from draft)."""
    code = _ACTION_TRACE_DETAIL_FROM_DRAFT if from_draft else _ACTION_TRACE_DETAIL
    data = f"{code}:{turn_id}:{step_name}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_trace_back_to_draft(turn_id: UUID) -> str:
    """Build callback_data for returning to the owner draft: tb:<uuid>."""
    data = f"{_ACTION_TRACE_BACK_TO_DRAFT}:{turn_id}"
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

    actions = {
        _ACTION_VIEW_TRACE,
        _ACTION_TRACE_DETAIL,
        _ACTION_TRACE_PAGE,
        _ACTION_TRACE_JSON,
        _ACTION_VIEW_TRACE_FROM_DRAFT,
        _ACTION_TRACE_DETAIL_FROM_DRAFT,
        _ACTION_TRACE_BACK_TO_DRAFT,
    }
    if code not in actions:
        return None

    if code == _ACTION_TRACE_PAGE:
        try:
            return TraceCallbackData(action=code, page=int(parts[1]))
        except (ValueError, IndexError):
            return None

    if code in {_ACTION_TRACE_DETAIL, _ACTION_TRACE_DETAIL_FROM_DRAFT}:
        try:
            return TraceCallbackData(
                action=code,
                turn_id=UUID(parts[1]),
                step=parts[2] if len(parts) > 2 else None,
            )
        except (ValueError, IndexError):
            return None

    # vt, vtd, tj, tb — optional trailing page for vt/vtd (A10).
    try:
        turn_id = UUID(parts[1])
    except (ValueError, IndexError):
        return None
    page: int | None = None
    if code in {_ACTION_VIEW_TRACE, _ACTION_VIEW_TRACE_FROM_DRAFT} and len(parts) > 2:
        try:
            page = int(parts[2])
        except ValueError:
            return None
    return TraceCallbackData(action=code, turn_id=turn_id, page=page)


def trace_list_keyboard(
    turns: list[tuple[UUID, str]], page: int, total_pages: int,
) -> InlineKeyboardMarkup:
    """Keyboard for the /turnos list with turn buttons + pagination."""
    buttons: list[list[InlineKeyboardButton]] = []

    # One button per turn. The current page travels in the callback so the
    # detail's "Volver a turnos" returns to this exact page (A10).
    for turn_id, short_id in turns:
        buttons.append([
            InlineKeyboardButton(
                text=f"🔍 Traza {short_id}",
                callback_data=encode_trace_view(turn_id, page=page),
            ),
        ])

    # Pagination row.
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="◀️ Anterior",
                callback_data=encode_trace_page(page - 1),
            )
        )
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton(
                text="Siguiente ▶️",
                callback_data=encode_trace_page(page + 1),
            )
        )
    if nav_row:
        buttons.append(nav_row)

    # Escape back to the owner panel (the /turnos legacy list had none — A10).
    buttons.append([
        InlineKeyboardButton(
            text="🔙 Volver al menú",
            callback_data=encode_menu("root"),
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def trace_detail_keyboard(
    turn_id: UUID,
    timings: dict[str, float] | None = None,
    from_draft: bool = False,
    page: int = 0,
) -> InlineKeyboardMarkup:
    """Keyboard with per-step buttons and export/back actions.

    ``from_draft`` swaps the "back to turns" action for a "back to draft"
    button so owners can return to the pending approval they entered from.
    ``page`` is the turns-list page to restore when pressing "Volver a turnos"
    (A10); it defaults to 0 for direct /traza entries.
    """
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
                callback_data=encode_trace_detail(turn_id, step_key, from_draft=from_draft),
            ),
        ])

    # Bottom row: export JSON + back (to the turns list, or the draft when entered from it).
    back_button = (
        InlineKeyboardButton(
            text="🔙 Volver al borrador",
            callback_data=encode_trace_back_to_draft(turn_id),
        )
        if from_draft
        else InlineKeyboardButton(
            text="🔙 Volver a turnos",
            callback_data=encode_trace_page(page),
        )
    )
    buttons.append([
        InlineKeyboardButton(
            text="📥 Exportar JSON",
            callback_data=encode_trace_json(turn_id),
        ),
        back_button,
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def step_detail_keyboard(turn_id: UUID, from_draft: bool = False) -> InlineKeyboardMarkup:
    """Keyboard with a single "Back to trace" button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 Volver a traza",
                    callback_data=encode_trace_view(turn_id, from_draft=from_draft),
                ),
            ],
        ]
    )


# ---- Patch draft_keyboard with Trace button ----
_draft_base = draft_keyboard


def draft_keyboard(
    turn_id: UUID, chat_id: int | None = None, *, show_quality_feedback: bool = False
) -> InlineKeyboardMarkup:
    """Aprobar / Corregir / Escalar + versiones + Traza / Nota."""
    base = _draft_base(turn_id, show_quality_feedback=show_quality_feedback)
    # Version nav row (v1 port): prev | regenerate | next
    base.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="◀ Anterior",
                callback_data=encode_callback("prev", turn_id),
            ),
            InlineKeyboardButton(
                text="🔄 Regenerar",
                callback_data=encode_callback("regen", turn_id),
            ),
            InlineKeyboardButton(
                text="Siguiente ▶",
                callback_data=encode_callback("next", turn_id),
            ),
        ]
    )
    note_cb = encode_add_note(chat_id) if chat_id is not None else encode_add_note(0)
    base.inline_keyboard.append([
        InlineKeyboardButton(
            text="🔍 Traza",
            callback_data=encode_trace_view(turn_id, from_draft=True),
        ),
        InlineKeyboardButton(
            text="📝 Agregar nota",
            callback_data=note_cb,
        ),
    ])
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


# ---- Staging queue helpers (sp: promote / sd: discard) ----


def encode_staging_promote(candidate_id: UUID) -> str:
    """Build callback_data for promote: sp:<uuid>."""
    data = f"{_ACTION_STAGING_PROMOTE}:{candidate_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_staging_discard(candidate_id: UUID) -> str:
    """Build callback_data for discard: sd:<uuid>."""
    data = f"{_ACTION_STAGING_DISCARD}:{candidate_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_staging_discard_confirm(candidate_id: UUID) -> str:
    """Build callback_data for discard confirm: sd:<uuid>:confirm (A4)."""
    data = f"{_ACTION_STAGING_DISCARD}:{candidate_id}:confirm"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_staging_discard_cancel(candidate_id: UUID) -> str:
    """Build callback_data for discard cancel: sd:<uuid>:cancel (A4)."""
    data = f"{_ACTION_STAGING_DISCARD}:{candidate_id}:cancel"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_staging_callback(data: str) -> tuple[str, UUID] | None:
    """Parse staging callback into (action, candidate_id) or None.

    ``sp:<uuid>`` → (promote, id). ``sd:<uuid>`` → (discard, id) — the first
    tap of the two-step discard (A4). ``sd:<uuid>:confirm`` and
    ``sd:<uuid>:cancel`` → (discard_confirm|discard_cancel, id).
    """
    if not data or ":" not in data:
        return None
    code, raw = data.split(":", 1)
    action = {
        _ACTION_STAGING_PROMOTE: "promote",
        _ACTION_STAGING_DISCARD: "discard",
    }.get(code)
    if action is None:
        return None
    suffix = ""
    if action == "discard" and ":" in raw:
        raw, suffix = raw.rsplit(":", 1)
    try:
        candidate_id = UUID(raw)
    except ValueError:
        return None
    if suffix:
        mapped = {"confirm": "discard_confirm", "cancel": "discard_cancel"}.get(suffix)
        return (mapped, candidate_id) if mapped is not None else None
    return action, candidate_id


def staging_candidate_keyboard(candidate_id: UUID) -> InlineKeyboardMarkup:
    """Promote / Discard inline keyboard for one staging example candidate."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Promover",
                    callback_data=encode_staging_promote(candidate_id),
                ),
                InlineKeyboardButton(
                    text="🗑 Descartar",
                    callback_data=encode_staging_discard(candidate_id),
                ),
            ]
        ]
    )


def staging_discard_confirm_keyboard(candidate_id: UUID) -> InlineKeyboardMarkup:
    """Two-step discard confirm (A4): YES discards, NO returns to the candidate."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Sí, descartar",
                    callback_data=encode_staging_discard_confirm(candidate_id),
                ),
                InlineKeyboardButton(
                    text="❌ No, mantener",
                    callback_data=encode_staging_discard_cancel(candidate_id),
                ),
            ]
        ]
    )


# ---- Memory approval helpers (mp: approve / md: discard) — F5 Pool 4 ----


def encode_memory_approve(fact_id: UUID) -> str:
    """Build callback_data for approve: mp:<uuid> (≤64 bytes)."""
    data = f"{_ACTION_MEMORY_APPROVE}:{fact_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_memory_discard(fact_id: UUID) -> str:
    """Build callback_data for discard: md:<uuid> (≤64 bytes)."""
    data = f"{_ACTION_MEMORY_DISCARD}:{fact_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_memory_approval_callback(data: str) -> tuple[str, UUID] | None:
    """Parse memory approval callback into (approve|discard, fact_id) or None.

    The payload carries ONLY the fact id (one UUID, 39 bytes ≤ 64): the
    vip_id is resolved server-side from the row (BR-15, A2).
    """
    if not data or ":" not in data:
        return None
    code, raw_id = data.split(":", 1)
    action = {
        _ACTION_MEMORY_APPROVE: "approve",
        _ACTION_MEMORY_DISCARD: "discard",
    }.get(code)
    if action is None:
        return None
    try:
        return action, UUID(raw_id)
    except ValueError:
        return None


def memory_pending_keyboard(fact_id: UUID) -> InlineKeyboardMarkup:
    """Approve / Discard inline keyboard for one pending memory fact."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Aprobar",
                    callback_data=encode_memory_approve(fact_id),
                ),
                InlineKeyboardButton(
                    text="🗑 Descartar",
                    callback_data=encode_memory_discard(fact_id),
                ),
            ]
        ]
    )


# ---- Link kick (Fase 6): link:<action>:<event_id> — ≤64 bytes ----
_LINK_ACTIONS: tuple[tuple[str, str], ...] = (
    ("expel", "❌ Expulsar"),
    ("disable", "🚫 Inhabilitar"),
    ("keep", "✅ Mantener"),
)


def link_kick_keyboard(event_id: str) -> InlineKeyboardMarkup:
    """Expel / Disable / Keep inline keyboard for a kicked-VIP notification."""
    buttons: list[list[InlineKeyboardButton]] = []
    for action, label in _LINK_ACTIONS:
        data = f"link:{action}:{event_id}"
        if len(data.encode("utf-8")) > 64:
            raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
        buttons.append([InlineKeyboardButton(text=label, callback_data=data)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def parse_link_callback(data: str) -> tuple[str, str] | None:
    """Parse link callback into (action, event_id) or None (A4)."""
    if not data or not data.startswith("link:"):
        return None
    parts = data.split(":", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    action, event_id = parts[1], parts[2]
    if action not in {"expel", "disable", "keep"}:
        return None
    return action, event_id


# ---- Hierarchical owner menu (buttons instead of raw slash commands) ----

MENU_ROOT_TEXT = "🌸 Panel de Diana\n\nElige una categoría:"

MENU_CATEGORY_TEXT: dict[str, str] = {
    "vips": "👥 Mis VIPs\nGestiona quién tiene acceso especial y qué sabe Diana de cada uno.",
    "review": (
        "💬 Revisar mensajes\n\n"
        "Aprobar, corregir o escalar un mensaje de Diana se hace con los botones "
        "que aparecen debajo de cada mensaje propuesto — no hace falta ningún comando.\n\n"
        "Aquí abajo solo está la opción para cuando una escalación fue una falsa alarma."
    ),
    "sandbox": "🧪 Modo de prueba\nPrueba cómo responde Diana sin avisar a nadie real.",
    "metrics": "📊 Métricas y aprendizaje\nCómo está funcionando Diana esta semana.",
    "history": "🔍 Historial y diagnóstico\nPara entender qué hizo Diana en un caso puntual.",
    "sombra": (
        "🤖 Modo sombra\n\n"
        "Aquí puedes revisar lo que Diana está aprendiendo en silencio: "
        "cuántas veces habría enviado sola, la confianza por VIP comparada "
        "con los umbrales y el mensaje que habría mandado. Es solo "
        "información — nada de esto cambia cómo responde hoy."
    ),
    "config": "⚙️ Configuración\n\nControla el comportamiento del bot. Por ahora solo está disponible el Modo Entrenamiento.",
    "personalidad": (
        "🎭 Personalidad y reglas\n\n"
        "Revisa y edita cómo habla Diana: su descripción, las reglas de tono y "
        "estilo, sus datos personales, patrones de voz, políticas y agenda. "
        "Cada cambio se guarda como una versión nueva (el historial permite "
        "volver atrás) y aplica de inmediato, sin reiniciar el bot."
    ),
}

MENU_EVENT_LIST_TEXT = (
    "📅 Eventos temporales\n\n"
    "Diana tendrá presente este contexto solo mientras el evento esté vigente."
)
MENU_EVENT_EMPTY_TEXT = (
    "📅 No hay eventos temporales.\n\n"
    "Crea uno para darle contexto a Diana por un tiempo limitado."
)
MENU_EVENT_CREATE_BODY_PROMPT = (
    "¿Qué le digo a Diana?\n\n"
    "Escribe el texto del evento (ej. \"este fin de semana hay promoción 2x1\").\n\n"
    "Usa /cancelar para abortar."
)
MENU_EVENT_DURATION_PROMPT = (
    "¿Cuánto tiempo debe durar?\n\n"
    "Elige una duración o una fecha específica:"
)
MENU_EVENT_CUSTOM_START_PROMPT = (
    "¿Cuándo empieza?\n\n"
    "Escribe \"ahora\", una duración desde ahora (ej. \"2 horas\") o una fecha "
    "(ej. \"2026-08-20 18:00\").\n\n"
    "Usa /cancelar para abortar."
)
MENU_EVENT_CUSTOM_END_PROMPT = (
    "¿Hasta cuándo?\n\n"
    "Escribe una duración desde el inicio (ej. \"2 días\") o una fecha "
    "(ej. \"2026-08-22\").\n\n"
    "Usa /cancelar para abortar."
)
MENU_EVENT_CONFIRM_TEMPLATE = (
    "📅 Confirma el evento:\n\n"
    "{body}\n\n"
    "🕐 Desde: {start}\n"
    "🕐 Hasta: {end}"
)
MENU_EVENT_EDIT_BODY_PROMPT = (
    "Escribe el nuevo texto del evento.\n\n"
    "Usa /cancelar para abortar."
)
MENU_EVENT_EDIT_DURATION_PROMPT = (
    "¿Cuánto tiempo debe durar?\n\n"
    "Elige una duración o una fecha específica:"
)


@dataclass
class MenuCallback:
    """Parsed menu callback data."""

    category: str
    action: str | None = None
    vip_user_id: int | None = None
    event_id: UUID | None = None
    extra: str | None = None  # sandbox profile name, fact key, note index


def encode_menu(category: str, action: str | None = None) -> str:
    """Build callback_data for the owner menu: m:<category>[:<action>]."""
    data = f"{_ACTION_MENU}:{category}" if action is None else f"{_ACTION_MENU}:{category}:{action}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_menu_vip(user_id: int) -> str:
    """Build callback_data for VIP detail: m:vip:<user_id>."""
    data = f"{_ACTION_MENU}:vip:{user_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_menu_vip_action(user_id: int, action: str) -> str:
    """Build callback_data for VIP action: m:vip:<user_id>:<action>."""
    data = f"{_ACTION_MENU}:vip:{user_id}:{action}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_menu_sandbox_profile(profile: str) -> str:
    """Build callback_data for sandbox profile selection: m:sandbox:activate_p:<profile>."""
    data = f"{_ACTION_MENU}:sandbox:activate_p:{profile}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_menu_persona(action: str, extra: str | None = None) -> str:
    """Build callback_data for the personalidad menu: m:personalidad:<action>[:<extra>]."""
    data = f"{_ACTION_MENU}:personalidad:{action}"
    if extra is not None:
        data = f"{data}:{extra}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_menu_event(event_id: UUID) -> str:
    """Build callback_data for event detail: m:event:<uuid>."""
    data = f"{_ACTION_MENU}:event:{event_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_menu_event_action(event_id: UUID, action: str) -> str:
    """Build callback_data for an event action: m:event:<uuid>:<action>."""
    data = f"{_ACTION_MENU}:event:{event_id}:{action}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def parse_menu_callback(data: str) -> MenuCallback | None:
    """Parse menu callback_data into MenuCallback, or None if not a menu callback."""
    if not data or not data.startswith(f"{_ACTION_MENU}:"):
        return None
    rest = data[len(_ACTION_MENU) + 1 :]
    if not rest:
        return None
    parts = rest.split(":")

    category = parts[0]

    if category == "vip" and len(parts) >= 2:
        try:
            vip_user_id = int(parts[1])
        except ValueError:
            return None
        if len(parts) == 2:
            return MenuCallback(category="vip", action=str(vip_user_id), vip_user_id=vip_user_id)
        action = parts[2]
        extra = ":".join(parts[3:]) if len(parts) > 3 else None
        return MenuCallback(category="vip", action=action, vip_user_id=vip_user_id, extra=extra)

    if category == "sandbox" and len(parts) >= 3 and parts[1] == "activate_p":
        profile = ":".join(parts[2:])
        return MenuCallback(category="sandbox", action="activate_p", extra=profile)

    if category == "event" and len(parts) >= 2:
        try:
            event_id = UUID(parts[1])
        except ValueError:
            # Create-mode: m:event:<action> (no event exists yet).
            action = parts[1]
            extra = ":".join(parts[2:]) if len(parts) > 2 else None
            return MenuCallback(category="event", action=action, extra=extra)
        if len(parts) == 2:
            return MenuCallback(category="event", event_id=event_id)
        action = parts[2]
        extra = ":".join(parts[3:]) if len(parts) > 3 else None
        return MenuCallback(category="event", action=action, event_id=event_id, extra=extra)

    action = parts[1] if len(parts) > 1 else None
    extra = ":".join(parts[2:]) if len(parts) > 2 else None
    return MenuCallback(category=category, action=action, extra=extra)


def _menu_back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="🔙 Volver", callback_data=encode_menu("root"))]


def menu_root_keyboard(show_persona: bool = False) -> InlineKeyboardMarkup:
    """Main menu: the logical categories (VIPs, Review, Sandbox, Metrics, History, Events, Shadow, Config).

    ``show_persona`` adds the "Personalidad y reglas" category (Item 3), gated by
    ``FEATURE_PERSONA_ADMIN_ENABLED`` so the default layout is unchanged.
    """
    rows = [
        [InlineKeyboardButton(text="👥 Mis VIPs", callback_data=encode_menu("vips"))],
        [InlineKeyboardButton(text="💬 Revisar mensajes", callback_data=encode_menu("review"))],
        [InlineKeyboardButton(text="🧪 Modo de prueba", callback_data=encode_menu("sandbox"))],
        [InlineKeyboardButton(text="📊 Métricas y aprendizaje", callback_data=encode_menu("metrics"))],
        [InlineKeyboardButton(text="🔍 Historial y diagnóstico", callback_data=encode_menu("history"))],
        [InlineKeyboardButton(text="📅 Eventos temporales", callback_data=encode_menu("event"))],
        [InlineKeyboardButton(text="🤖 Modo sombra", callback_data=encode_menu("sombra"))],
    ]
    if show_persona:
        rows.append([
            InlineKeyboardButton(
                text="🎭 Personalidad y reglas",
                callback_data=encode_menu("personalidad"),
            )
        ])
    rows.append([InlineKeyboardButton(text="⚙️ Configuración", callback_data=encode_menu("config"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_shadow_keyboard() -> InlineKeyboardMarkup:
    """Shadow-mode consult section: summary, per-VIP trust and would-be drafts."""
    rows = [
        [
            InlineKeyboardButton(
                text="📊 Resumen y umbrales",
                callback_data=encode_menu("sombra", "summary"),
            )
        ],
        [
            InlineKeyboardButton(
                text="👥 Confianza por VIP",
                callback_data=encode_menu("sombra", "vips"),
            )
        ],
        [
            InlineKeyboardButton(
                text="💬 Borradores y decisiones",
                callback_data=encode_menu("sombra", "decisions"),
            )
        ],
        _menu_back_row(),
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_vip_list_keyboard(
    vips_data: list[tuple[int, str | None]],
) -> InlineKeyboardMarkup:
    """One button per VIP with display name or user ID, plus register and back."""
    buttons: list[list[InlineKeyboardButton]] = []
    for user_id, display_name in vips_data:
        label = display_name or str(user_id)
        buttons.append([
            InlineKeyboardButton(
                text=f"👤 {label}",
                callback_data=encode_menu_vip(user_id),
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="➕ Registrar nuevo VIP",
            callback_data=encode_menu("vips", "register"),
        ),
    ])
    buttons.append(_menu_back_row())
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def menu_vip_detail_keyboard(user_id: int, *, is_paused: bool = False) -> InlineKeyboardMarkup:
    """Per-VIP actions: toggle pausa, ficha, nota, dato, renombrar, eliminar, volver."""
    toggle_label = "🔓 Reanudar" if is_paused else "🔒 Pausar"
    toggle_action = "unpause" if is_paused else "pause"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Ver ficha", callback_data=encode_menu_vip_action(user_id, "profile"))],
            [
                InlineKeyboardButton(text="📝 Agregar nota", callback_data=encode_menu_vip_action(user_id, "note_add")),
            ],
            [
                InlineKeyboardButton(text="🏷 Agregar dato", callback_data=encode_menu_vip_action(user_id, "fact_add")),
            ],
            [InlineKeyboardButton(text="✏️ Renombrar", callback_data=encode_menu_vip_action(user_id, "rename"))],
            [InlineKeyboardButton(text="🗑 Eliminar", callback_data=encode_menu_vip_action(user_id, "delete"))],
            [
                InlineKeyboardButton(
                    text=toggle_label,
                    callback_data=encode_menu_vip_action(user_id, toggle_action),
                ),
            ],
            [
                InlineKeyboardButton(text="🔙 Volver a lista", callback_data=encode_menu("vips")),
                InlineKeyboardButton(text="🔙 Inicio", callback_data=encode_menu("root")),
            ],
        ]
    )


def menu_pause_duration_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Duration picker shown after tapping Pausar: 1 dia, 1 semana, 3 dias, 1 mes, indefinido."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 1 día",
                    callback_data=encode_menu_vip_action(user_id, "pause:1d"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 1 semana",
                    callback_data=encode_menu_vip_action(user_id, "pause:7d"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 3 días",
                    callback_data=encode_menu_vip_action(user_id, "pause:3d"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 1 mes",
                    callback_data=encode_menu_vip_action(user_id, "pause:1m"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="♾️ Indefinido",
                    callback_data=encode_menu_vip_action(user_id, "pause:indef"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Volver al perfil",
                    callback_data=encode_menu_vip(user_id),
                ),
            ],
        ]
    )


def menu_vip_profile_keyboard(
    user_id: int,
    *,
    show_generate: bool = False,
    notes: list | None = None,
    facts: dict | None = None,
) -> InlineKeyboardMarkup:
    """Back to VIP detail after viewing profile/ficha.

    With memory backfill wired (``show_generate=True``) the first row offers
    "🔄 Generar perfil" (callback ``profile_generate``) — the ficha-triggered
    enqueue of REQ-MEM-05. ``facts``/``notes`` (A9) add one per-item delete
    button per fact (``fact_del:<key>``) and note (``note_del:<i>``) so the
    ficha stops hiding capabilities the legacy /vip_note_del commands exposed.
    Defaults keep the output identical to the pre-Pool-2 keyboard (back-compat).
    """
    rows: list[list[InlineKeyboardButton]] = []
    if show_generate:
        rows.append([
            InlineKeyboardButton(
                text="🔄 Generar perfil",
                callback_data=encode_menu_vip_action(user_id, "profile_generate"),
            )
        ])
    for key in (facts or {}).keys():
        try:
            data = encode_menu_vip_action(user_id, f"fact_del:{key}")
        except ValueError:
            # A key too long for callback_data still shows in the ficha text
            # and stays reachable via the legacy command; skip its button.
            continue
        rows.append([InlineKeyboardButton(text=f"🗑 {key}", callback_data=data)])
    for i in range(1, len(notes or []) + 1):
        rows.append([
            InlineKeyboardButton(
                text=f"🗑 Nota {i}",
                callback_data=encode_menu_vip_action(user_id, f"note_del:{i}"),
            )
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 Volver al perfil", callback_data=encode_menu_vip(user_id)),
        InlineKeyboardButton(text="🔙 Inicio", callback_data=encode_menu("root")),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_back_keyboard(dest: str) -> InlineKeyboardMarkup:
    """Simple back-only keyboard with a single Volver button for terminal actions."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Volver", callback_data=dest)]]
    )


# ---------------------------------------------------------------------------
# Eventos temporales — owner admin for time-bounded context events
# ---------------------------------------------------------------------------


def menu_event_list_keyboard(events: list[EphemeralEventRecord]) -> InlineKeyboardMarkup:
    """One button per open event (first 30 chars of body), plus create and home."""
    buttons: list[list[InlineKeyboardButton]] = []
    for ev in events:
        title = (ev.body or "").strip()[:30] or str(ev.id)[:8]
        buttons.append([
            InlineKeyboardButton(text=f"📅 {title}", callback_data=encode_menu_event(ev.id)),
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Crear evento", callback_data=encode_menu("event", "create")),
    ])
    buttons.append([InlineKeyboardButton(text="🔙 Inicio", callback_data=encode_menu("root"))])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def menu_event_detail_keyboard(event: EphemeralEventRecord) -> InlineKeyboardMarkup:
    """Per-event actions: pausar/reanudar, modificar, terminar, eliminar, volver."""
    toggle_label = "▶️ Reanudar" if event.is_paused else "⏸️ Pausar"
    toggle_action = "resume" if event.is_paused else "pause"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=toggle_label,
                    callback_data=encode_menu_event_action(event.id, toggle_action),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Modificar",
                    callback_data=encode_menu_event_action(event.id, "modify"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🛑 Terminar antes",
                    callback_data=encode_menu_event_action(event.id, "terminate"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Eliminar",
                    callback_data=encode_menu_event_action(event.id, "delete"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Volver a la lista",
                    callback_data=encode_menu("event"),
                ),
            ],
        ]
    )


def menu_event_confirm_delete_keyboard(event_id: UUID) -> InlineKeyboardMarkup:
    """Confirm or cancel event deletion."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Sí, eliminar",
                    callback_data=encode_menu_event_action(event_id, "delete_confirm"),
                ),
                InlineKeyboardButton(
                    text="❌ No, cancelar",
                    callback_data=encode_menu_event(event_id),
                ),
            ],
        ]
    )


def menu_event_terminate_confirm_keyboard(event_id: UUID) -> InlineKeyboardMarkup:
    """Confirm or cancel ending an event before its end date."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Sí, terminar",
                    callback_data=encode_menu_event_action(event_id, "terminate_confirm"),
                ),
                InlineKeyboardButton(
                    text="❌ No, cancelar",
                    callback_data=encode_menu_event(event_id),
                ),
            ],
        ]
    )


def menu_event_duration_keyboard(event_id: UUID | None = None) -> InlineKeyboardMarkup:
    """Quick durations: create mode (event_id=None) or edit mode (event_id set).

    Create-mode callbacks carry no event id (``m:event:dur_*``); edit-mode
    callbacks are event-scoped (``m:event:<uuid>:dur_*``) so the tapped
    duration is applied to that event.
    """
    def _cb(action: str) -> str:
        return (
            encode_menu_event_action(event_id, action)
            if event_id is not None
            else encode_menu("event", action)
        )

    if event_id is not None:
        back, back_label = encode_menu_event(event_id), "🔙 Volver"
    else:
        back, back_label = encode_menu("event", "create_cancel"), "🔙 Cancelar"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Hoy", callback_data=_cb("dur_today"))],
            [InlineKeyboardButton(text="2 días", callback_data=_cb("dur_2d"))],
            [InlineKeyboardButton(text="3 días", callback_data=_cb("dur_3d"))],
            [InlineKeyboardButton(text="1 semana", callback_data=_cb("dur_1w"))],
            [InlineKeyboardButton(text="📅 Otra fecha", callback_data=_cb("dur_custom"))],
            [InlineKeyboardButton(text=back_label, callback_data=back)],
        ]
    )


def menu_event_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirm or cancel event creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Crear evento",
                    callback_data=encode_menu("event", "create_confirm"),
                ),
                InlineKeyboardButton(
                    text="❌ Cancelar",
                    callback_data=encode_menu("event", "create_cancel"),
                ),
            ],
        ]
    )


def menu_event_modify_keyboard(event_id: UUID) -> InlineKeyboardMarkup:
    """Modify sub-menu: edit text, edit duration, back to the detail."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Editar texto",
                    callback_data=encode_menu_event_action(event_id, "edit_text"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏰ Editar duración",
                    callback_data=encode_menu_event_action(event_id, "edit_duration"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Volver",
                    callback_data=encode_menu_event(event_id),
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Personalidad y reglas (Item 3) — owner admin for the persona catalog
# ---------------------------------------------------------------------------

_PERSONA_BACK = "personalidad"


def menu_personalidad_keyboard(active_channel: str = "vip") -> InlineKeyboardMarkup:
    """Sections of the Personalidad y reglas admin (back to root).

    Renders the channel selector row first (REQ-ATN-06); the active channel
    is marked with a checkmark. Channel callbacks are ``m:personalidad:channel:<c>``.
    """
    vip_marker = " ✅" if active_channel == "vip" else ""
    atn_marker = " ✅" if active_channel == "atencion" else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"👑 VIP{vip_marker}",
                    callback_data=encode_menu_persona("channel", "vip"),
                ),
                InlineKeyboardButton(
                    text=f"💼 Atención{atn_marker}",
                    callback_data=encode_menu_persona("channel", "atencion"),
                ),
            ],
            [InlineKeyboardButton(
                text="📝 Cómo habla Diana",
                callback_data=encode_menu_persona("persona"),
            )],
            [InlineKeyboardButton(
                text="✍️ Reglas de tono y estilo",
                callback_data=encode_menu_persona("rules"),
            )],
            [InlineKeyboardButton(
                text="👤 Datos personales",
                callback_data=encode_menu_persona("facts"),
            )],
            [InlineKeyboardButton(
                text="🗣️ Patrones de voz",
                callback_data=encode_menu_persona("patterns"),
            )],
            [InlineKeyboardButton(
                text="📜 Políticas de conducta",
                callback_data=encode_menu_persona("policies"),
            )],
            [InlineKeyboardButton(
                text="🗓️ Agenda",
                callback_data=encode_menu_persona("schedule"),
            )],
            [InlineKeyboardButton(
                text="🕘 Historial y restauración",
                callback_data=encode_menu_persona("history"),
            )],
            _menu_back_row(),
        ]
    )


def menu_persona_list_keyboard(
    items: list[tuple[str, str]],
    add_action: str | None,
    *,
    back_to: str = _PERSONA_BACK,
    item_action: str = "item",
) -> InlineKeyboardMarkup:
    """Dynamic item list: one row per (callback_extra, label), plus optional add + back."""
    buttons: list[list[InlineKeyboardButton]] = []
    for extra, label in items:
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=encode_menu_persona(item_action, extra),
            )
        ])
    if add_action is not None:
        buttons.append([
            InlineKeyboardButton(
                text="➕ Agregar",
                callback_data=encode_menu_persona(add_action),
            )
        ])
    buttons.append(
        _menu_back_row()
        if back_to == "root"
        else [InlineKeyboardButton(text="🔙 Volver", callback_data=encode_menu(back_to))]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def menu_persona_confirm_restore_keyboard(version_id: str) -> InlineKeyboardMarkup:
    """Confirm a version restore (destructive-ish, undoable but confirm anyway)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Sí, restaurar esta versión",
                    callback_data=encode_menu_persona("restore_ok", version_id),
                ),
            ],
            [InlineKeyboardButton(text="🔙 Cancelar", callback_data=encode_menu(_PERSONA_BACK))],
        ]
    )


def menu_review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚩 Marcar falsa alarma", callback_data=encode_menu("review", "fp"))],
            _menu_back_row(),
        ]
    )


def menu_sandbox_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Activar", callback_data=encode_menu("sandbox", "activate"))],
            [InlineKeyboardButton(text="🔴 Desactivar", callback_data=encode_menu("sandbox", "off"))],
            [InlineKeyboardButton(text="📄 Ver perfiles de prueba", callback_data=encode_menu("sandbox", "profiles"))],
            [InlineKeyboardButton(text="ℹ️ Ver estado actual", callback_data=encode_menu("sandbox", "status"))],
            [InlineKeyboardButton(text="🔄 Reiniciar prueba", callback_data=encode_menu("sandbox", "reset"))],
            _menu_back_row(),
        ]
    )


def menu_sandbox_profile_picker_keyboard(
    profiles: list[dict],
) -> InlineKeyboardMarkup:
    """Profile selection grid for sandbox activation step 3."""
    buttons: list[list[InlineKeyboardButton]] = []
    for prof in profiles:
        name = prof.get("name", "")
        label = prof.get("label", name) or name
        buttons.append([
            InlineKeyboardButton(
                text=f"🎭 {label}",
                callback_data=encode_menu_sandbox_profile(name),
            )
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Cancelar", callback_data=encode_menu("sandbox"))])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def encode_register_confirm(user_id: int) -> str:
    """Callback for register confirmation: m:register:confirm:<user_id>."""
    data = f"{_ACTION_MENU}:register:confirm:{user_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def encode_register_cancel() -> str:
    """Callback for register cancel: m:register:cancel."""
    data = f"{_ACTION_MENU}:register:cancel"
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data exceeds 64 bytes: {data!r}")
    return data


def menu_register_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Confirm or cancel VIP registration."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirmar",
                    callback_data=encode_register_confirm(user_id),
                ),
                InlineKeyboardButton(
                    text="❌ Cancelar",
                    callback_data=encode_register_cancel(),
                ),
            ],
        ]
    )


def menu_confirm_delete_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Confirm or cancel VIP deactivation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Sí, desactivar",
                    callback_data=encode_menu_vip_action(user_id, "delete_confirm"),
                ),
                InlineKeyboardButton(
                    text="❌ No, cancelar",
                    callback_data=encode_menu_vip(user_id),
                ),
            ],
        ]
    )


def menu_metrics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📈 Ver resumen semanal", callback_data=encode_menu("metrics", "summary"))],
            [InlineKeyboardButton(text="🧠 Ejemplos pendientes", callback_data=encode_menu("metrics", "staging"))],
            _menu_back_row(),
        ]
    )


def menu_history_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🕓 Ver turnos recientes", callback_data=encode_menu("history", "turns"))],
            [InlineKeyboardButton(text="🔬 Ver detalle de un turno", callback_data=encode_menu("history", "trace"))],
            _menu_back_row(),
        ]
    )


def menu_config_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    """Configuration keyboard with the training-mode toggle and the LLM admin."""
    toggle_text = "Modo Entrenamiento: ON ✅" if enabled else "Modo Entrenamiento: OFF ❌"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=encode_menu("config", "toggle"))],
            [InlineKeyboardButton(text="🤖 Modelo de IA", callback_data=encode_menu("config", "llm"))],
            _menu_back_row(),
        ]
    )


def menu_llm_keyboard() -> InlineKeyboardMarkup:
    """LLM admin: change the model at runtime (ADM-03) or reset to default."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Cambiar modelo",
                    callback_data=encode_menu("config", "llm_set"),
                ),
                InlineKeyboardButton(
                    text="🔄 Restablecer",
                    callback_data=encode_menu("config", "llm_reset"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Volver",
                    callback_data=encode_menu("config"),
                ),
            ],
        ]
    )


__all__ = [
    "MenuCallback",
    "TraceCallbackData",
    "doctrine_keyboard",
    "draft_keyboard",
    "encode_add_note",
    "encode_callback",
    "encode_doctrine_callback",
    "encode_doctrine_resolve_callback",
    "encode_doctrine_escalate_callback",
    "encode_menu",
    "encode_menu_event",
    "encode_menu_event_action",
    "encode_menu_persona",
    "encode_menu_sandbox_profile",
    "encode_menu_vip",
    "encode_menu_vip_action",
    "encode_metrics_back",
    "encode_metrics_export",
    "encode_register_cancel",
    "encode_register_confirm",
    "encode_staging_discard",
    "encode_staging_discard_confirm",
    "encode_staging_discard_cancel",
    "encode_staging_promote",
    "encode_trace_view",
    "encode_trace_detail",
    "encode_trace_page",
    "encode_trace_json",
    "encode_trace_back_to_draft",
    "link_kick_keyboard",
    "menu_back_keyboard",
    "menu_config_keyboard",
    "menu_confirm_delete_keyboard",
    "menu_event_confirm_delete_keyboard",
    "menu_event_confirm_keyboard",
    "menu_event_detail_keyboard",
    "menu_event_duration_keyboard",
    "menu_event_list_keyboard",
    "menu_event_modify_keyboard",
    "menu_event_terminate_confirm_keyboard",
    "menu_history_keyboard",
    "menu_metrics_keyboard",
    "menu_register_confirm_keyboard",
    "menu_review_keyboard",
    "menu_root_keyboard",
    "menu_sandbox_keyboard",
    "menu_sandbox_profile_picker_keyboard",
    "menu_pause_duration_keyboard",
    "menu_personalidad_keyboard",
    "menu_persona_confirm_restore_keyboard",
    "menu_persona_list_keyboard",
    "menu_vip_detail_keyboard",
    "menu_vip_list_keyboard",
    "menu_vip_profile_keyboard",
    "metrics_keyboard",
    "parse_callback",
    "parse_doctrine_callback",
    "parse_link_callback",
    "parse_menu_callback",
    "parse_metrics_callback",
    "parse_staging_callback",
    "parse_trace_callback",
    "staging_candidate_keyboard",
    "staging_discard_confirm_keyboard",
    "step_detail_keyboard",
    "trace_detail_keyboard",
    "trace_list_keyboard",
    "MENU_ROOT_TEXT",
    "MENU_CATEGORY_TEXT",
    "MENU_EVENT_CONFIRM_TEMPLATE",
    "MENU_EVENT_CREATE_BODY_PROMPT",
    "MENU_EVENT_CUSTOM_END_PROMPT",
    "MENU_EVENT_CUSTOM_START_PROMPT",
    "MENU_EVENT_DURATION_PROMPT",
    "MENU_EVENT_EDIT_BODY_PROMPT",
    "MENU_EVENT_EDIT_DURATION_PROMPT",
    "MENU_EVENT_EMPTY_TEXT",
    "MENU_EVENT_LIST_TEXT",
]
