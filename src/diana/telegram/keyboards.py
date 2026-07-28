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
# Staging queue (sp: promote, sd: discard) — ≤64 bytes
_ACTION_STAGING_PROMOTE = "sp"
_ACTION_STAGING_DISCARD = "sd"
# Hierarchical owner menu (m:<category> or m:<category>:<action>) — ≤64 bytes
_ACTION_MENU = "m"


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


def parse_staging_callback(data: str) -> tuple[str, UUID] | None:
    """Parse staging callback into (promote|discard, candidate_id) or None."""
    if not data or ":" not in data:
        return None
    code, raw_id = data.split(":", 1)
    action = {
        _ACTION_STAGING_PROMOTE: "promote",
        _ACTION_STAGING_DISCARD: "discard",
    }.get(code)
    if action is None:
        return None
    try:
        return action, UUID(raw_id)
    except ValueError:
        return None


def staging_candidate_keyboard(candidate_id: UUID) -> InlineKeyboardMarkup:
    """Promote / Discard inline keyboard for one staging example candidate."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Promote",
                    callback_data=encode_staging_promote(candidate_id),
                ),
                InlineKeyboardButton(
                    text="🗑 Discard",
                    callback_data=encode_staging_discard(candidate_id),
                ),
            ]
        ]
    )


# ---- Hierarchical owner menu (buttons instead of raw slash commands) ----

MENU_ROOT_TEXT = "🌸 Panel de Diana\n\nElegí una categoría:"

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
}


@dataclass
class MenuCallback:
    """Parsed menu callback data."""

    category: str
    action: str | None = None
    vip_user_id: int | None = None
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

    action = parts[1] if len(parts) > 1 else None
    return MenuCallback(category=category, action=action)


def _menu_back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="🔙 Volver", callback_data=encode_menu("root"))]


def menu_root_keyboard() -> InlineKeyboardMarkup:
    """Main menu: the 5 logical categories."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Mis VIPs", callback_data=encode_menu("vips"))],
            [InlineKeyboardButton(text="💬 Revisar mensajes", callback_data=encode_menu("review"))],
            [InlineKeyboardButton(text="🧪 Modo de prueba", callback_data=encode_menu("sandbox"))],
            [InlineKeyboardButton(text="📊 Métricas y aprendizaje", callback_data=encode_menu("metrics"))],
            [InlineKeyboardButton(text="🔍 Historial y diagnóstico", callback_data=encode_menu("history"))],
        ]
    )


def menu_vip_list_keyboard(
    vips_data: list[tuple[int, str | None]],
) -> InlineKeyboardMarkup:
    """One button per VIP with display name or user ID, plus back to root."""
    buttons: list[list[InlineKeyboardButton]] = []
    for user_id, display_name in vips_data:
        label = display_name or str(user_id)
        buttons.append([
            InlineKeyboardButton(
                text=f"👤 {label}",
                callback_data=encode_menu_vip(user_id),
            )
        ])
    buttons.append(_menu_back_row())
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def menu_vip_detail_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Per-VIP actions: ficha, nota, dato, renombrar, eliminar, volver."""
    uid = str(user_id)
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
                InlineKeyboardButton(text="🔙 Volver a lista", callback_data=encode_menu("vips")),
                InlineKeyboardButton(text="🔙 Inicio", callback_data=encode_menu("root")),
            ],
        ]
    )


def menu_vip_profile_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Back to VIP detail after viewing profile/ficha."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 Volver al perfil", callback_data=encode_menu_vip(user_id)),
                InlineKeyboardButton(text="🔙 Inicio", callback_data=encode_menu("root")),
            ],
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
            [InlineKeyboardButton(text="🔄 Reiniciar conversacion de prueba", callback_data=encode_menu("sandbox", "reset"))],
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


__all__ = [
    "MenuCallback",
    "TraceCallbackData",
    "doctrine_keyboard",
    "draft_keyboard",
    "encode_callback",
    "encode_doctrine_callback",
    "encode_doctrine_resolve_callback",
    "encode_doctrine_escalate_callback",
    "encode_menu",
    "encode_menu_sandbox_profile",
    "encode_menu_vip",
    "encode_menu_vip_action",
    "encode_metrics_back",
    "encode_metrics_export",
    "encode_staging_discard",
    "encode_staging_promote",
    "encode_trace_view",
    "encode_trace_detail",
    "encode_trace_page",
    "encode_trace_json",
    "metrics_keyboard",
    "parse_callback",
    "parse_doctrine_callback",
    "parse_menu_callback",
    "parse_metrics_callback",
    "parse_staging_callback",
    "parse_trace_callback",
    "staging_candidate_keyboard",
    "step_detail_keyboard",
    "trace_detail_keyboard",
    "trace_list_keyboard",
    "MENU_ROOT_TEXT",
    "MENU_CATEGORY_TEXT",
    "menu_root_keyboard",
    "menu_vip_list_keyboard",
    "menu_vip_detail_keyboard",
    "menu_vip_profile_keyboard",
    "menu_review_keyboard",
    "menu_sandbox_keyboard",
    "menu_sandbox_profile_picker_keyboard",
    "menu_confirm_delete_keyboard",
    "menu_metrics_keyboard",
    "menu_history_keyboard",
]
