"""Hierarchical owner menu — profile-centric actions + multi-step wizards.

Replaces the flat /menu command list with 5 logical categories (VIPs,
Revisar mensajes, Modo de prueba, Metricas, Historial). Each category opens
a submenu of buttons. Actions execute directly or start a guided multi-step
flow (sandbox activation via forwarded message, add note, add fact, rename).

Registered BEFORE the catch-all callback router and the admin router so that
m:* menu callbacks and menu-session text are consumed first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from aiogram import Bot, Router
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, Message

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_shadow_service import AdminShadowService
from diana.application.admin_trace_service import AdminTraceService
from diana.application.ephemeral_event_service import EphemeralEventService
from diana.application.persona_admin_service import PersonaAdminService
from diana.application.ports import (
    EphemeralEventRecord,
    TrainingModeStore,
    VipStore,
)
from diana.application.profile_admin_service import ProfileAdminService
from diana.application.sandbox import SandboxService
from diana.application.staging_service import StagingService
from diana.application.turn_coordinator import TurnCoordinator
from diana.telegram.handlers.persona_admin import (
    _current_channel,
    dispatch_personalidad,
    handle_persona_edit_text,
)
from diana.telegram.handlers.admin import (
    format_sandbox_perfiles,
    format_vips_list,
    is_private_owner_message,
)
from diana.telegram.handlers.staging import (
    format_staging_candidate_body,
    load_pending_staging_list,
)
from diana.telegram.keyboards import (
    MENU_CATEGORY_TEXT,
    MENU_EVENT_CONFIRM_TEMPLATE,
    MENU_EVENT_CREATE_BODY_PROMPT,
    MENU_EVENT_CUSTOM_END_PROMPT,
    MENU_EVENT_CUSTOM_START_PROMPT,
    MENU_EVENT_DURATION_PROMPT,
    MENU_EVENT_EDIT_BODY_PROMPT,
    MENU_EVENT_EDIT_DURATION_PROMPT,
    MENU_EVENT_EMPTY_TEXT,
    MENU_EVENT_LIST_TEXT,
    MENU_ROOT_TEXT,
    MenuCallback,
    encode_menu,
    encode_menu_vip,
    menu_back_keyboard,
    menu_config_keyboard,
    menu_confirm_delete_keyboard,
    menu_event_confirm_delete_keyboard,
    menu_event_confirm_keyboard,
    menu_event_detail_keyboard,
    menu_event_duration_keyboard,
    menu_event_list_keyboard,
    menu_event_modify_keyboard,
    menu_event_terminate_confirm_keyboard,
    menu_history_keyboard,
    menu_metrics_keyboard,
    menu_pause_duration_keyboard,
    menu_personalidad_keyboard,
    menu_register_confirm_keyboard,
    menu_review_keyboard,
    menu_root_keyboard,
    menu_sandbox_keyboard,
    menu_sandbox_profile_picker_keyboard,
    menu_shadow_keyboard,
    menu_vip_detail_keyboard,
    menu_vip_list_keyboard,
    menu_vip_profile_keyboard,
    metrics_keyboard,
    parse_menu_callback,
    staging_candidate_keyboard,
    trace_list_keyboard,
)

logger = logging.getLogger("diana.telegram")

_CONFIRM_EXPIRED_UX = "Esta confirmación expiró, vuelve a intentarlo."
_SESSION_EXPIRED_UX = "Tu operación expiró, vuelve a intentarlo."

# ---------------------------------------------------------------------------
# MenuSessionStore — process-local FSM for multi-step menu flows
# ---------------------------------------------------------------------------

DEFAULT_MENU_TTL = timedelta(minutes=15)

MenuSessionKind = Literal[
    "sandbox_forward", "sandbox_profile", "note", "fact", "rename", "register_vip",
    "persona_edit",
    "event_body", "event_duration", "event_custom_start", "event_custom_end",
    "event_edit_body",
]


@dataclass
class MenuSession:
    """A single in-progress multi-step menu operation."""

    kind: MenuSessionKind
    vip_user_id: int | None = None
    sandbox_chat_id: int | None = None
    persona_section: str | None = None
    persona_target: str | None = None
    persona_channel: str = "vip"
    event_body: str | None = None
    event_start_at: datetime | None = None
    event_end_at: datetime | None = None
    event_id: UUID | None = None
    last_bot_message_id: int | None = None
    last_chat_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MenuSessionStore:
    """Process-local FSM for multi-step menu flows (note, fact, rename, sandbox).

    Mirrors the ``CorrectSessionStore`` pattern: in-memory only, 15-min TTL,
    owner_id-keyed. Restart clears all sessions.
    """

    def __init__(
        self,
        *,
        ttl: timedelta = DEFAULT_MENU_TTL,
        clock: Any = None,
    ) -> None:
        self._sessions: dict[int, MenuSession] = {}
        self._pending_vip_names: dict[int, str] = {}
        self._confirmations: dict[int, datetime] = {}
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(UTC))

    def start(self, owner_id: int, kind: MenuSessionKind, **kwargs: Any) -> None:
        session = MenuSession(kind=kind, **kwargs)
        # Use the store clock (injected in tests) so TTL expiry is deterministic.
        session.created_at = self._clock()
        self._sessions[owner_id] = session

    def _resolve(self, owner_id: int) -> MenuSession | None:
        session = self._sessions.get(owner_id)
        if session is None:
            return None
        if self._clock() - session.created_at > self._ttl:
            self._sessions.pop(owner_id, None)
            return None
        return session

    def get(self, owner_id: int) -> MenuSession | None:
        return self._resolve(owner_id)

    def pop(self, owner_id: int) -> MenuSession | None:
        session = self._resolve(owner_id)
        if session is not None:
            self._sessions.pop(owner_id, None)
        return session

    def has_active(self, owner_id: int) -> bool:
        return self._resolve(owner_id) is not None

    def status(self, owner_id: int) -> Literal["none", "live", "expired"]:
        """Pure session state query (no popping): none | live | expired."""
        session = self._sessions.get(owner_id)
        if session is None:
            return "none"
        if self._clock() - session.created_at > self._ttl:
            return "expired"
        return "live"

    def cancel(self, owner_id: int) -> None:
        self._sessions.pop(owner_id, None)

    def store_pending_vip_name(self, owner_id: int, name: str) -> None:
        self._pending_vip_names[owner_id] = name

    def pop_pending_vip_name(self, owner_id: int) -> str | None:
        return self._pending_vip_names.pop(owner_id, None)

    # -- destructive-confirmation TTL (A7) --------------------------------
    # Delete/register confirmation buttons must not stay valid forever. A new
    # confirmation overwrites the previous one, and TTL bounds how long an
    # unconfirmed prompt can still execute. Kept separate from _sessions so an
    # active confirmation never captures plain text through HasActiveMenuSession.

    def record_confirmation(self, owner_id: int) -> None:
        """Mark the instant a destructive confirmation prompt was shown (A7)."""
        self._confirmations[owner_id] = self._clock()

    def confirmation_live(self, owner_id: int) -> bool:
        """True if a confirmation prompt is within TTL and not yet spent."""
        issued = self._confirmations.get(owner_id)
        if issued is None:
            return False
        if self._clock() - issued > self._ttl:
            self._confirmations.pop(owner_id, None)
            return False
        return True

    def consume_confirmation(self, owner_id: int) -> bool:
        """Validate and spend a confirmation in one step (A7)."""
        live = self.confirmation_live(owner_id)
        self._confirmations.pop(owner_id, None)
        return live


class HasActiveMenuSession(Filter):
    """Aiogram filter: True when the owner has a live (or just-expired) MenuSession.

    Slash-commands are never swallowed: they must route to their own command
    handlers (e.g. /list_vips while a rename session is pending). Forwarded
    messages keep their ``forward_origin`` so they still match even if the
    forwarded content happens to start with "/".

    Expired sessions still match (A6) so the text handler can warn "Tu operación
    expiró" instead of silently swallowing the owner's input.
    """

    def __init__(self, sessions: MenuSessionStore) -> None:
        self.sessions = sessions

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None:
            return False
        if self.sessions.status(message.from_user.id) == "none":
            return False
        text = (message.text or "").strip()
        if text.startswith("/") and message.forward_origin is None:
            return False
        return True


# ---------------------------------------------------------------------------
# Category keyboards — "vips" is dynamic, "config" is parameterized (needs state),
# rest are static parameterless factories.
# ---------------------------------------------------------------------------

_CATEGORY_KEYBOARDS: dict[str, Any] = {
    "vips": None,  # dynamic — needs VIP list from DB
    "review": menu_review_keyboard,
    "sandbox": menu_sandbox_keyboard,
    "metrics": menu_metrics_keyboard,
    "history": menu_history_keyboard,
    "sombra": menu_shadow_keyboard,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# F5 Pool 4 (F5-06): status icons for the 🧠 Memoria section of the ficha.
_MEMORY_STATUS_ICONS = {
    "auto": "✅",
    "approved": "✅",
    "pending_owner": "⏳ pendiente",
    "discarded": "🗑 descartado",
}

_MEMORY_SECTION_MAX = 50

_TRUST_TREND_ICONS = {"up": "▲", "down": "▼", "flat": "→"}


def _memory_section_lines(
    memory_rows: list[dict], *, max_facts: int = _MEMORY_SECTION_MAX
) -> tuple[list[str], int]:
    """Render the 🧠 Memoria section; returns (lines, pending_count).

    Empty rows → empty lines (no orphan header). Text comes from
    ``content.texto`` (canonical) or ``content.fact``; the status icon
    shows the owner the approval state of each fact.
    """
    if not memory_rows:
        return [], 0
    lines = ["\n🧠 Memoria:"]
    pending = 0
    for row in memory_rows[:max_facts]:
        category = row.get("category") or "?"
        content = row.get("content") or {}
        texto = str(content.get("texto") or content.get("fact") or "")
        status = row.get("status") or "auto"
        if status == "pending_owner":
            pending += 1
        icon = _MEMORY_STATUS_ICONS.get(status, "✅")
        lines.append(f"  • [{category}] {texto} · {icon}")
    return lines, pending


def _trust_section_lines(trust_rows: list[dict]) -> list[str]:
    """Render the 🔐 Confianza section (EA-06); empty rows → no lines.

    The "collapsible section" pattern of this codebase = a header + lines that
    never break the Telegram render (no orphan header when there are no rows).
    Each row: category, score (0.00-1.00), trend icon, counts and the date of
    the last correction. User-facing text is neutral Mexican Spanish.
    """
    if not trust_rows:
        return []
    lines = ["\n🔐 Confianza:"]
    for row in trust_rows:
        category = row.get("category") or "?"
        score = float(row.get("trust_score") or 0.0)
        trend = _TRUST_TREND_ICONS.get(row.get("trend"), "→")
        parts = [f"  • [{category}] {score:.2f} {trend}"]
        parts.append(f"autónomos {row.get('autonomous_count', 0)}")
        parts.append(f"correcciones {row.get('correction_count', 0)}")
        last = row.get("last_correction_at")
        if last:
            parts.append(f"última {str(last)[:10]}")
        lines.append(" · ".join(parts))
    return lines


def _profile_history_lines(
    history_rows: list[dict], *, max_versions: int = 5
) -> list[str]:
    """Render the 📚 Historial de versiones section (EA-06).

    Newest-first (the repo returns newest-first); each entry shows the version
    number, the date and the diff summary truncated to a readable snippet.
    """
    if not history_rows:
        return []
    lines = ["\n📚 Historial de versiones:"]
    for row in history_rows[:max_versions]:
        version = row.get("version", "?")
        created = row.get("created_at")
        when = str(created)[:10] if created else "—"
        diff = (row.get("diff_summary") or "").strip()
        snippet = _truncate_text(diff, max_len=90) if diff else "sin resumen"
        lines.append(f"  • v{version} · {when} — {snippet}")
    return lines


def _truncate_text(text: str, max_len: int = 90) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _format_vip_profile(result: Any) -> str:
    """Format a ``ProfileAdminResult`` for display."""
    if result.status == "vip_not_found":
        return "VIP no encontrado."
    name = result.display_name or str(result.telegram_user_id)
    memory_lines, pending_count = _memory_section_lines(result.memory or [])
    # F5 Pool 4 (F5-06): the manual ficha is NOT replaced — the semantic
    # memory is an extra section. The "Sin datos todavia" empty card only
    # applies when there is no manual data AND no memory either (the
    # diagnosed "perfil generado pero no se ve nada" case is fixed here).
    # Evo-Agente Fase 5 (EA-06): trust rows also keep the card away — a VIP
    # with only trust history still gets a ficha with the 🔐 Confianza section.
    if (
        result.status == "profile_empty"
        and not memory_lines
        and not (result.trust_budget or [])
        and not (result.profile_history or [])
    ):
        return f"Ficha de {name}\n\nSin datos todavia."

    content = result.content or {}
    facts = content.get("facts", {})
    notes = content.get("notes", [])

    lines = [f"👤 Ficha de {name}"]

    if facts:
        lines.append("\n📌 Datos:")
        for k, v in facts.items():
            lines.append(f"  • {k}: {v}")

    if notes:
        lines.append("\n📝 Notas:")
        for i, note in enumerate(notes, 1):
            if isinstance(note, str):
                text, date_str = note, ""
            else:
                text = note.get("text", str(note))
                date_str = note.get("date", "")
            prefix = f"({date_str}) " if date_str else ""
            lines.append(f"  {i}. {prefix}{text}")

    lines.extend(memory_lines)
    if pending_count > 0:
        lines.append(f"\nHay {pending_count} hechos por aprobar — usa /memoria.")

    # Evo-Agente Fase 5 (EA-06): the 🔐 Confianza section — additive, follows
    # the memory section; empty rows render nothing (no orphan header).
    lines.extend(_trust_section_lines(result.trust_budget or []))
    # Evo-Agente Fase 5 (EA-06): 📚 Historial de versiones — additive, follows
    # the trust section; empty rows render nothing (no orphan header).
    lines.extend(_profile_history_lines(result.profile_history or []))

    return "\n".join(lines)


async def _show(message: Message, text: str, keyboard: Any) -> None:
    """Edit the existing menu message in place; fall back to a new one."""
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await message.answer(text, reply_markup=keyboard)


async def _edit_or_answer(
    bot: Bot,
    text: str,
    *,
    session: MenuSession | None = None,
    fallback: Message | None = None,
    keyboard: Any = None,
) -> None:
    """Edit the stored session message; fall back to a new message."""
    if session and session.last_chat_id and session.last_bot_message_id:
        try:
            await bot.edit_message_text(
                chat_id=session.last_chat_id,
                message_id=session.last_bot_message_id,
                text=text,
                reply_markup=keyboard,
            )
            return
        except Exception:
            pass
    if fallback is not None:
        await fallback.answer(text, reply_markup=keyboard)


def _extract_chat_id_from_forward(message: Message) -> int | None:
    """Best-effort extraction of a chat_id from a forwarded message."""
    forward_origin = message.forward_origin

    if forward_origin is not None:
        # MessageOriginChat
        sender_chat = getattr(forward_origin, "sender_chat", None)
        if sender_chat is not None:
            return getattr(sender_chat, "id", None)
        # MessageOriginChannel
        chat = getattr(forward_origin, "chat", None)
        if chat is not None:
            return getattr(chat, "id", None)
        # MessageOriginUser — user ID is the chat ID for private chats
        sender_user = getattr(forward_origin, "sender_user", None)
        if sender_user is not None:
            return getattr(sender_user, "id", None)

    # Legacy fallbacks (older messages / non-origin forwards)
    fwd_chat = getattr(message, "forward_from_chat", None)
    if fwd_chat is not None:
        return getattr(fwd_chat, "id", None)
    fwd_user = getattr(message, "forward_from", None)
    if fwd_user is not None:
        return getattr(fwd_user, "id", None)

    return None


def _extract_user_from_forward(message: Message) -> tuple[int, str | None] | None:
    """Extract (user_id, display_name) from a forwarded user message, or None.

    Returns ``None`` when the forwarded message is not from a user (e.g. chat,
    channel, or hidden sender).
    """
    forward_origin = message.forward_origin
    if forward_origin is not None:
        sender_user = getattr(forward_origin, "sender_user", None)
        if sender_user is not None:
            display = sender_user.full_name or None
            return (sender_user.id, display)
        return None

    # Legacy forward_from (User object)
    fwd_user = getattr(message, "forward_from", None)
    if fwd_user is not None:
        display = fwd_user.full_name or None
        return (fwd_user.id, display)
    return None


def _is_vip_paused(vip) -> bool:
    """True if vip.paused_until is set and in the future (normalizes naive datetimes)."""
    if vip is None or vip.paused_until is None:
        return False
    paused = vip.paused_until
    if paused.tzinfo is None:
        paused = paused.replace(tzinfo=UTC)
    return paused > datetime.now(UTC)


# ---------------------------------------------------------------------------
# build_menu_router
# ---------------------------------------------------------------------------


def build_menu_router(
    *,
    owner_telegram_id: int,
    vips: VipStore,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    shadow_admin: AdminShadowService | None = None,
    sandbox: SandboxService | None = None,
    staging: StagingService | None = None,
    coordinator: TurnCoordinator | None = None,
    profile_admin: ProfileAdminService | None = None,
    persona_admin: PersonaAdminService | None = None,
    feature_persona_admin_enabled: bool = False,
    menu_sessions: MenuSessionStore | None = None,
    config_store: TrainingModeStore | None = None,
    history_seed: object | None = None,
    backfill_queue: object | None = None,
    ephemeral_event_service: EphemeralEventService | None = None,
) -> Router:
    """Build the router serving /start, /menu, m:* callbacks, and menu-session text."""
    router = Router(name="menu")
    sessions = menu_sessions or MenuSessionStore()
    # Flag-gate the whole panel (not just the button): with the feature off the
    # admin surface is inert, matching the sandbox/staging pattern.
    persona_admin = persona_admin if feature_persona_admin_enabled else None

    def _is_owner(message: Message) -> bool:
        return is_private_owner_message(message, owner_telegram_id)

    # ---- /start, /menu ----

    @router.message(Command("start", "menu"))
    async def on_menu(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        await message.answer(
            MENU_ROOT_TEXT,
            reply_markup=menu_root_keyboard(show_persona=feature_persona_admin_enabled),
        )

    # ---- m:* callbacks ----

    @router.callback_query(lambda c: (c.data or "").startswith("m:"))
    async def on_menu_callback(callback: CallbackQuery, **_: Any) -> None:
        actor_id = callback.from_user.id if callback.from_user else None
        if actor_id != owner_telegram_id:
            await callback.answer("No autorizado", show_alert=True)
            return

        parsed = parse_menu_callback(callback.data or "")
        if parsed is None:
            await callback.answer()
            return

        await callback.answer()

        # --- root ---
        if parsed.category == "root":
            if isinstance(callback.message, Message):
                await _show(
                    callback.message,
                    MENU_ROOT_TEXT,
                    menu_root_keyboard(show_persona=feature_persona_admin_enabled),
                )
            return

        msg = callback.message
        if not isinstance(msg, Message):
            return

        # --- category submenu (action is None) ---
        # m:event:<uuid> (detail) is a concrete event callback, so it is routed
        # to _dispatch_action below just like m:vip:<id>.
        if (
            parsed.action is None
            and parsed.category != "vip"
            and not (parsed.category == "event" and parsed.event_id is not None)
        ):
            if parsed.category == "event":
                await _render_event_list(msg, ephemeral_event_service, actor_id)
                return

            if parsed.category == "vips":
                records = await vips.list_active()
                if not records:
                    await _show(msg, "No hay VIPs activos.", menu_root_keyboard())
                    return
                vips_data = [(r.telegram_user_id, r.display_name) for r in records]
                await _show(
                    msg,
                    "👥 Mis VIPs\nSelecciona un perfil para ver sus opciones.",
                    menu_vip_list_keyboard(vips_data),
                )
                return

            if parsed.category == "config":
                if config_store is None:
                    await _show(
                        msg,
                        "Configuración no disponible.",
                        menu_back_keyboard(encode_menu("root")),
                    )
                    return
                text = MENU_CATEGORY_TEXT.get(parsed.category)
                if text is None:
                    return
                enabled = await config_store.is_enabled()
                await _show(msg, text, menu_config_keyboard(enabled))
                return

            if parsed.category == "personalidad":
                if persona_admin is None:
                    await _show(
                        msg,
                        "Personalidad y reglas no disponible.",
                        menu_back_keyboard(encode_menu("root")),
                    )
                    return
                text = MENU_CATEGORY_TEXT.get(parsed.category)
                if text is None:
                    return
                channel = _current_channel(sessions, actor_id)
                await _show(
                    msg, text, menu_personalidad_keyboard(active_channel=channel)
                )
                return

            build_kb = _CATEGORY_KEYBOARDS.get(parsed.category)
            text = MENU_CATEGORY_TEXT.get(parsed.category)
            if build_kb is None or text is None:
                return
            await _show(msg, text, build_kb())
            return

        # --- dispatch concrete actions ---
        result = await _dispatch_action(
            msg,
            parsed=parsed,
            actor_id=actor_id,
            vips=vips,
            admin_trace=admin_trace,
            admin_metrics=admin_metrics,
            shadow_admin=shadow_admin,
            sandbox=sandbox,
            staging=staging,
            coordinator=coordinator,
            profile_admin=profile_admin,
            persona_admin=persona_admin,
            sessions=sessions,
            config_store=config_store,
            history_seed=history_seed,
            backfill_queue=backfill_queue,
            ephemeral_event_service=ephemeral_event_service,
        )
        if result == "confirm_expired":
            # A3-style late alert: the early empty answer already cleared the
            # spinner; the message edit shows the redirect, the alert explains.
            try:
                await callback.answer(_CONFIRM_EXPIRED_UX, show_alert=True)
            except Exception:
                logger.exception(
                    "menu_confirm_expired_answer_failed",
                    extra={"callback_data": callback.data or "", "actor_id": actor_id},
                )

    # ---- text capture for multi-step flows ----

    @router.message(Command("cancelar"))
    async def on_cancel_command(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        owner_id = message.from_user.id  # type: ignore[union-attr]
        if sessions.pop(owner_id) is not None:
            await message.reply("Operacion cancelada.")
        else:
            await message.reply("No hay ninguna operación activa para cancelar.")

    @router.message(HasActiveMenuSession(sessions))
    async def on_menu_session_text(message: Message, bot: Bot, **_: Any) -> None:
        if not _is_owner(message):
            return
        owner_id = message.from_user.id  # type: ignore[union-attr]

        # A6: a wizard that outlived its TTL must warn, not swallow the input.
        if sessions.status(owner_id) == "expired":
            sessions.cancel(owner_id)
            await message.reply(_SESSION_EXPIRED_UX)
            return

        session = sessions.pop(owner_id)
        if session is None:
            return

        if session.kind == "sandbox_forward":
            await _handle_sandbox_forward(message, bot, session, sandbox, sessions)
        elif session.kind == "sandbox_profile":
            # Owner typed text instead of tapping a profile button: keep the
            # wizard alive so the next tap/input still lands here.
            sessions.start(
                owner_id,
                "sandbox_profile",
                sandbox_chat_id=session.sandbox_chat_id,
                last_bot_message_id=session.last_bot_message_id,
                last_chat_id=session.last_chat_id,
            )
            await _edit_or_answer(
                bot,
                "Usa los botones para seleccionar un perfil.\n\n"
                "Usa /cancelar para abortar.",
                session=session, fallback=message,
            )
        elif session.kind == "persona_edit":
            await handle_persona_edit_text(message, bot, session, persona_admin, sessions)
        elif session.kind == "register_vip":
            await _handle_register_forward(message, bot, session, vips, sessions)
        elif session.kind == "note":
            await _handle_note_text(message, bot, session, profile_admin, sessions)
        elif session.kind == "fact":
            await _handle_fact_text(message, bot, session, profile_admin, sessions)
        elif session.kind == "rename":
            await _handle_rename_text(message, bot, session, vips, sessions)
        elif session.kind == "event_body":
            await _handle_event_body_text(
                message, bot, session, ephemeral_event_service, sessions
            )
        elif session.kind == "event_duration":
            # The duration step is button-driven; free text re-shows the picker.
            sessions.start(
                owner_id,
                "event_duration",
                event_body=session.event_body,
                event_start_at=session.event_start_at,
                event_end_at=session.event_end_at,
                event_id=session.event_id,
                last_bot_message_id=session.last_bot_message_id,
                last_chat_id=session.last_chat_id,
            )
            await _edit_or_answer(
                bot,
                MENU_EVENT_DURATION_PROMPT,
                session=session,
                fallback=message,
                keyboard=menu_event_duration_keyboard(session.event_id),
            )
        elif session.kind == "event_custom_start":
            await _handle_event_custom_start_text(
                message, bot, session, ephemeral_event_service, sessions
            )
        elif session.kind == "event_custom_end":
            await _handle_event_custom_end_text(
                message, bot, session, ephemeral_event_service, sessions
            )
        elif session.kind == "event_edit_body":
            await _handle_event_edit_body_text(
                message, bot, session, ephemeral_event_service, sessions
            )

    return router


# ---------------------------------------------------------------------------
# Action dispatcher
# ---------------------------------------------------------------------------


async def _dispatch_action(
    message: Message,
    *,
    parsed: MenuCallback,
    actor_id: int,
    vips: VipStore,
    admin_trace: AdminTraceService | None,
    admin_metrics: AdminMetricsService | None,
    shadow_admin: AdminShadowService | None = None,
    sandbox: SandboxService | None,
    staging: StagingService | None,
    coordinator: TurnCoordinator | None,
    profile_admin: ProfileAdminService | None,
    persona_admin: PersonaAdminService | None = None,
    sessions: MenuSessionStore,
    config_store: TrainingModeStore | None = None,
    history_seed: object | None = None,
    backfill_queue: object | None = None,
    ephemeral_event_service: EphemeralEventService | None = None,
) -> None:
    category = parsed.category
    action = parsed.action

    # ==================================================================
    # Modo sombra — consulta (read-only)
    # ==================================================================
    if category == "sombra" and action in ("summary", "vips", "decisions"):
        if shadow_admin is None:
            await _show(
                message,
                "El modo sombra no está disponible.",
                menu_back_keyboard(encode_menu("sombra")),
            )
            return
        try:
            if action == "summary":
                body = await shadow_admin.render_summary()
            elif action == "vips":
                body = await shadow_admin.render_by_vip()
            else:
                body = await shadow_admin.render_decisions()
        except Exception:
            logger.exception("shadow_menu_render_failed")
            await _show(
                message,
                "Error del sistema al cargar el modo sombra. Reintenta más tarde.",
                menu_back_keyboard(encode_menu("sombra")),
            )
            return
        await _show(message, body, menu_shadow_keyboard())
        return

    # ==================================================================
    # Eventos temporales — detail, actions, and the create/edit wizards
    # ==================================================================
    if category == "event":
        return await _dispatch_event_action(
            message,
            parsed=parsed,
            actor_id=actor_id,
            service=ephemeral_event_service,
            sessions=sessions,
        )

    # ==================================================================
    # VIP detail & per-VIP actions
    # ==================================================================
    if category == "vip" and parsed.vip_user_id is not None:
        user_id = parsed.vip_user_id

        # Show VIP detail card
        if action == str(user_id):
            vip = await vips.get_by_telegram_user_id(user_id)
            if vip is None or not vip.is_active:
                # A13: a stale m:vip button (VIP gone or deactivated) must not
                # render a card whose actions fail one by one; send the owner
                # back to the active list with a warning.
                await _show(
                    message,
                    "El VIP ya no existe o fue desactivado.",
                    menu_back_keyboard(encode_menu("vips")),
                )
                return
            name = vip.display_name or str(user_id)
            is_paused = _is_vip_paused(vip)
            status_line = "Estado: 🔒 Pausado\n" if is_paused else "Estado: 🟢 Activo\n"
            text = (
                f"👤 Perfil de {name}\n"
                f"ID: {user_id}\n\n"
                f"{status_line}"
                "Selecciona una acción:"
            )
            await _show(message, text, menu_vip_detail_keyboard(user_id, is_paused=is_paused))
            return

        # --- profile (view ficha) ---
        if action == "profile":
            if profile_admin is None:
                await _show(
                    message,
                    "Gestion de perfiles no disponible.",
                    menu_back_keyboard(encode_menu_vip(user_id)),
                )
                return
            result = await profile_admin.show_profile(actor_id, user_id)
            content = result.content or {}
            await _show(
                message,
                _format_vip_profile(result),
                menu_vip_profile_keyboard(
                    user_id,
                    show_generate=backfill_queue is not None,
                    notes=content.get("notes", []) if isinstance(content, dict) else None,
                    facts=content.get("facts", {}) if isinstance(content, dict) else None,
                ),
            )
            return

        # --- generate memory profile (enqueue backfill, REQ-MEM-05) ---
        if action == "profile_generate":
            if backfill_queue is None:
                await _show(
                    message,
                    "Perfil de memoria no disponible.",
                    menu_vip_profile_keyboard(user_id),
                )
                return
            schedule = getattr(backfill_queue, "schedule_enqueue", None)
            if callable(schedule):
                schedule(user_id)
            await _show(
                message,
                "🔄 Perfil en cola — te aviso por DM cuando avance.",
                menu_vip_profile_keyboard(user_id, show_generate=True),
            )
            return

        # --- add note ---
        if action == "note_add":
            if profile_admin is None:
                await _show(
                    message,
                    "Gestion de perfiles no disponible.",
                    menu_back_keyboard(encode_menu_vip(user_id)),
                )
                return
            sessions.start(
                actor_id,
                "note",
                vip_user_id=user_id,
                last_bot_message_id=message.message_id,
                last_chat_id=message.chat.id,
            )
            await _show(
                message,
                f"Escribe la nota para el VIP {user_id}.\n\n"
                "Usa /cancelar para abortar.",
                None,
            )
            return

        # --- delete note ---
        if action == "note_del":
            if profile_admin is None:
                await _show(
                    message,
                    "Gestion de perfiles no disponible.",
                    menu_back_keyboard(encode_menu_vip(user_id)),
                )
                return
            try:
                idx = int(parsed.extra or "0")
            except ValueError:
                await _show(
                    message,
                    "Número de nota inválido.",
                    menu_back_keyboard(encode_menu_vip(user_id)),
                )
                return
            result = await profile_admin.delete_note(actor_id, user_id, idx)
            kb = menu_back_keyboard(encode_menu_vip(user_id))
            if result.status == "note_deleted":
                await _show(
                    message,
                    f"Nota {idx} eliminada de {result.display_name or user_id}.",
                    kb,
                )
            else:
                await _show(
                    message,
                    f"No se pudo eliminar la nota: {result.status}",
                    kb,
                )
            return

        # --- add fact ---
        if action == "fact_add":
            if profile_admin is None:
                await _show(
                    message,
                    "Gestion de perfiles no disponible.",
                    menu_back_keyboard(encode_menu_vip(user_id)),
                )
                return
            sessions.start(
                actor_id,
                "fact",
                vip_user_id=user_id,
                last_bot_message_id=message.message_id,
                last_chat_id=message.chat.id,
            )
            await _show(
                message,
                f"Escribe el dato para el VIP {user_id} en formato:\n"
                "clave: valor\n\n"
                "Usa /cancelar para abortar.",
                None,
            )
            return

        # --- delete fact ---
        if action == "fact_del":
            if profile_admin is None:
                await _show(
                    message,
                    "Gestion de perfiles no disponible.",
                    menu_back_keyboard(encode_menu_vip(user_id)),
                )
                return
            key = (parsed.extra or "").strip()
            if not key:
                await _show(
                    message,
                    "Especifica la clave del dato a eliminar.",
                    menu_back_keyboard(encode_menu_vip(user_id)),
                )
                return
            result = await profile_admin.delete_fact(actor_id, user_id, key)
            kb = menu_back_keyboard(encode_menu_vip(user_id))
            if result.status == "fact_deleted":
                await _show(
                    message,
                    f"Dato '{key}' eliminado de {result.display_name or user_id}.",
                    kb,
                )
            else:
                await _show(
                    message,
                    f"No se pudo eliminar el dato: {result.status}",
                    kb,
                )
            return

        # --- rename ---
        if action == "rename":
            sessions.start(
                actor_id,
                "rename",
                vip_user_id=user_id,
                last_bot_message_id=message.message_id,
                last_chat_id=message.chat.id,
            )
            await _show(
                message,
                f"Escribe el nuevo nombre para el VIP {user_id}.\n\n"
                "Usa /cancelar para abortar.",
                None,
            )
            return

        # --- delete confirmation ---
        if action == "delete":
            sessions.record_confirmation(actor_id)
            await _show(
                message,
                f"¿Desactivar al VIP {user_id}?\n\n"
                "Se desactivara, no se borrara permanentemente.",
                menu_confirm_delete_keyboard(user_id),
            )
            return

        # --- delete confirmed ---
        if action == "delete_confirm":
            # A7: a confirm button from a stale message must not execute.
            if not sessions.consume_confirmation(actor_id):
                await _show(
                    message, _CONFIRM_EXPIRED_UX, menu_back_keyboard(encode_menu("vips"))
                )
                return "confirm_expired"
            ok = await vips.deactivate(user_id)
            kb = menu_back_keyboard(encode_menu("vips"))
            if ok:
                await _show(message, f"VIP {user_id} desactivado.", kb)
            else:
                await _show(message, f"No se encontró al VIP {user_id}.", kb)
            return

        # --- pause (pausar) ---
        if action == "pause":
            duration = parsed.extra
            # No duration yet — show the duration picker submenu
            if duration is None:
                vip = await vips.get_by_telegram_user_id(user_id)
                if vip is None or not vip.is_active:
                    await _show(message, f"VIP {user_id} no encontrado o inactivo.", menu_back_keyboard(encode_menu("vips")))
                    return
                name = vip.display_name if vip and vip.display_name else str(user_id)
                await _show(
                    message,
                    f"⏸ Pausar a {name}\n\n"
                    "Selecciona la duración de la pausa:",
                    menu_pause_duration_keyboard(user_id),
                )
                return

            vip = await vips.get_by_telegram_user_id(user_id)
            if vip is None or not vip.is_active:
                await _show(message, f"VIP {user_id} no encontrado o inactivo.", menu_back_keyboard(encode_menu("vips")))
                return

            now = datetime.now(UTC)
            if duration == "1d":
                paused_until = now + timedelta(days=1)
            elif duration == "7d":
                paused_until = now + timedelta(days=7)
            elif duration == "3d":
                paused_until = now + timedelta(days=3)
            elif duration == "1m":
                paused_until = now + timedelta(days=30)
            elif duration == "indef":
                paused_until = datetime(2099, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
            else:
                await _show(message, "Duracion no valida.", menu_back_keyboard(encode_menu_vip(user_id)))
                return

            try:
                await vips.pause_vip(vip.id, paused_until)
            except ValueError:
                await _show(message, "El VIP ya no existe o fue desactivado.", menu_back_keyboard(encode_menu("vips")))
                return

            vip = await vips.get_by_telegram_user_id(user_id)
            is_paused = _is_vip_paused(vip)
            name = vip.display_name if vip and vip.display_name else str(user_id)
            status_line = "Estado: 🔒 Pausado\n" if is_paused else "Estado: 🟢 Activo\n"
            text = (
                f"👤 Perfil de {name}\n"
                f"ID: {user_id}\n\n"
                f"{status_line}"
                "Selecciona una acción:"
            )
            await _show(
                message, text, menu_vip_detail_keyboard(user_id, is_paused=is_paused)
            )
            return

        # --- unpause (reanudar) ---
        if action == "unpause":
            vip = await vips.get_by_telegram_user_id(user_id)
            if vip is None or not vip.is_active:
                await _show(message, f"VIP {user_id} no encontrado o inactivo.", menu_back_keyboard(encode_menu("vips")))
                return
            try:
                await vips.unpause_vip(vip.id)
            except ValueError:
                await _show(message, "El VIP ya no existe o fue desactivado.", menu_back_keyboard(encode_menu("vips")))
                return
            # Re-query to get updated state
            vip = await vips.get_by_telegram_user_id(user_id)
            name = vip.display_name if vip and vip.display_name else str(user_id)
            text = (
                f"👤 Perfil de {name}\n"
                f"ID: {user_id}\n\n"
                "Estado: 🟢 Activo\n"
                "Selecciona una acción:"
            )
            await _show(
                message, text, menu_vip_detail_keyboard(user_id, is_paused=False)
            )
            return

        await _show(
            message,
            "Accion no disponible.",
            menu_back_keyboard(encode_menu("vips")),
        )
        return

    # ==================================================================
    # Register VIP (start the forward-flow)
    # ==================================================================
    if category == "vips" and action == "register":
        sessions.start(
            actor_id,
            "register_vip",
            last_bot_message_id=message.message_id,
            last_chat_id=message.chat.id,
        )
        await _show(
            message,
            "Para registrar un nuevo VIP, reenvíame un mensaje "
            "de la persona que quieras agregar.\n\n"
            "Tiene que ser un mensaje reenviado desde el chat "
            "con esa persona.\n\n"
            "Usa /cancelar para abortar.",
            None,
        )
        return

    # ==================================================================
    # Register confirm/cancel (buttons from confirmation)
    # ==================================================================
    if category == "register":
        if action == "cancel":
            await _show(
                message,
                "Registro cancelado.",
                menu_back_keyboard(encode_menu("vips")),
            )
            return

        if action == "confirm":
            # A7: a confirm button from a stale message must not register the
            # VIP with outdated context (pending name could already be gone).
            if not sessions.consume_confirmation(actor_id):
                await _show(
                    message, _CONFIRM_EXPIRED_UX, menu_back_keyboard(encode_menu("vips"))
                )
                return "confirm_expired"
            try:
                user_id = int(parsed.extra or "0")
            except (ValueError, TypeError):
                await _show(
                    message,
                    "ID de usuario inválido.",
                    menu_back_keyboard(encode_menu("vips")),
                )
                return

            # Use the display name from the forwarded message if available.
            pending_name = sessions.pop_pending_vip_name(actor_id)

            result = await vips.add(user_id, display_name=pending_name)
            schedule = getattr(history_seed, "schedule_seed_for_new_vip", None)
            if callable(schedule):
                schedule(user_id)
            enqueue = getattr(backfill_queue, "schedule_enqueue", None)
            if callable(enqueue):
                enqueue(user_id)
            name = result.display_name or str(user_id)
            await _show(
                message,
                f"✅ VIP registrado: {name} (ID: {user_id})",
                menu_back_keyboard(encode_menu("vips")),
            )
            return

        await _show(
            message,
            "Acción no disponible.",
            menu_back_keyboard(encode_menu("vips")),
        )
        return

    # ==================================================================
    # Sandbox
    # ==================================================================
    if category == "sandbox":
        if sandbox is None:
            await _show(
                message,
                "El modo de prueba no está disponible.",
                menu_back_keyboard(encode_menu("root")),
            )
            return

        if action == "activate":
            sessions.start(
                actor_id,
                "sandbox_forward",
                last_bot_message_id=message.message_id,
                last_chat_id=message.chat.id,
            )
            await _show(
                message,
                "Para activar el modo de prueba, reenvía un mensaje del chat "
                "que quieres poner en modo sandbox.\n\n"
                "Usa /cancelar para abortar.",
                None,
            )
            return

        if action == "activate_p":
            profile = parsed.extra or "nuevo"
            # Try to get the chat_id from a pending session
            session = sessions.get(actor_id)
            chat_id = session.sandbox_chat_id if session else None
            if chat_id is None:
                await _show(
                    message,
                    "No se encontró el chat. Inicia de nuevo la activación.",
                    menu_back_keyboard(encode_menu("sandbox")),
                )
                sessions.cancel(actor_id)
                return
            sessions.cancel(actor_id)
            sandbox.activate(chat_id, profile)
            await _show(
                message,
                f"Modo de prueba activado en chat {chat_id} con perfil '{profile}'.",
                menu_back_keyboard(encode_menu("sandbox")),
            )
            return

        if action == "profiles":
            await _show(
                message,
                format_sandbox_perfiles(sandbox.list_profiles()),
                menu_back_keyboard(encode_menu("sandbox")),
            )
            return

        if action == "status":
            await _show(
                message,
                sandbox.format_estado(),
                menu_back_keyboard(encode_menu("sandbox")),
            )
            return

        if action == "off":
            focus = sandbox.get_focus_chat_id()
            if focus is None:
                await _show(
                    message,
                    "No hay modo de prueba activo.",
                    menu_back_keyboard(encode_menu("sandbox")),
                )
                return
            was = sandbox.deactivate(focus)
            await _show(
                message,
                f"Modo de prueba desactivado (chat {focus})."
                if was
                else "No habia modo de prueba activo.",
                menu_back_keyboard(encode_menu("sandbox")),
            )
            return

        if action == "reset":
            focus = sandbox.get_focus_chat_id()
            if focus is None or not sandbox.is_active(focus):
                await _show(
                    message,
                    "No hay modo de prueba activo.",
                    menu_back_keyboard(encode_menu("sandbox")),
                )
                return
            if coordinator is None:
                await _show(
                    message,
                    "Error del sistema: no se puede reiniciar ahora.",
                    menu_back_keyboard(encode_menu("sandbox")),
                )
                return
            await coordinator.reset_chat_session(focus, reason="menu_reset")
            await _show(
                message,
                f"Conversación de prueba reiniciada (chat {focus}).",
                menu_back_keyboard(encode_menu("sandbox")),
            )
            return

        await _show(message, "Accion no disponible.", menu_back_keyboard(encode_menu("sandbox")))
        return

    # ==================================================================
    # Review
    # ==================================================================
    if category == "review" and action == "fp":
        await _show(
            message,
            "Usa el comando:\n/fp <id_del_turno>\n\n"
            "Úsalo cuando Diana escaló algo que en realidad no era un problema.\n"
            "El id del turno aparece en Historial -> Ver turnos recientes.",
            menu_back_keyboard(encode_menu("review")),
        )
        return

    # ==================================================================
    # Metrics
    # ==================================================================
    if category == "metrics":
        if action == "summary":
            if admin_metrics is None:
                await _show(
                    message,
                    "Metricas no disponibles todavia.",
                    menu_back_keyboard(encode_menu("metrics")),
                )
                return
            try:
                body, status = await admin_metrics.render_week_summary()
            except Exception:
                logger.exception("Error loading metrics summary")
                await _show(
                    message,
                    "Error del sistema al cargar métricas. Reintenta más tarde.",
                    menu_back_keyboard(encode_menu("metrics")),
                )
                return
            kb = metrics_keyboard() if status == "ok" else menu_back_keyboard(
                encode_menu("metrics")
            )
            await _show(message, body, kb)
            return

        if action == "staging":
            token, rows = await load_pending_staging_list(staging=staging)
            if token == "unavailable":
                await _show(
                    message,
                    "El aprendizaje por ejemplos no está disponible.",
                    menu_back_keyboard(encode_menu("metrics")),
                )
                return
            if token == "empty":
                await _show(
                    message,
                    "No hay ejemplos pendientes de revision.",
                    menu_back_keyboard(encode_menu("metrics")),
                )
                return
            for i, candidate in enumerate(rows):
                text = format_staging_candidate_body(candidate)
                kb = staging_candidate_keyboard(candidate.id)
                if i == 0:
                    await _show(message, text, kb)
                else:
                    await message.answer(text, reply_markup=kb)
            return

    # ==================================================================
    # History
    # ==================================================================
    if category == "history" and action == "turns":
        back = menu_back_keyboard(encode_menu("history"))
        if admin_trace is None:
            await _show(message, "El historial no está disponible.", back)
            return
        try:
            view = await admin_trace.render_turns_page(0)
        except Exception:
            logger.exception("Error querying traces")
            await _show(
                message,
                "Error del sistema al consultar el historial. Reintenta más tarde.",
                back,
            )
            return
        if view.empty:
            await _show(message, "No hay turnos recientes.", back)
            return
        kb = trace_list_keyboard(
            view.turns_data, page=view.page, total_pages=view.total_pages
        )
        await _show(message, view.text, kb)
        return

    if category == "history" and action == "trace":
        await _show(
            message,
            "Usa el comando:\n/traza <id_del_turno>",
            menu_back_keyboard(encode_menu("history")),
        )
        return

    # ==================================================================
    # Config — training mode toggle
    # ==================================================================
    if category == "personalidad":
        await dispatch_personalidad(
            message,
            parsed=parsed,
            actor_id=actor_id,
            persona_admin=persona_admin,
            sessions=sessions,
        )
        return

    if category == "config" and action == "toggle":
        if config_store is None:
            await _show(
                message,
                "Configuración no disponible.",
                menu_back_keyboard(encode_menu("root")),
            )
            return
        current = await config_store.is_enabled()
        new_state = not current
        await config_store.set_enabled(new_state)
        logger.info(
            "training_mode_toggle",
            extra={
                "actor_id": actor_id,
                "enabled": new_state,
            },
        )
        await _show(message, MENU_CATEGORY_TEXT["config"], menu_config_keyboard(new_state))
        return

    # Unknown / unmapped action — should not normally happen.
    await _show(
        message,
        "Esa opción todavía no está disponible.",
        menu_back_keyboard(encode_menu("root")),
    )


# ---------------------------------------------------------------------------
# Multi-step text handlers
# ---------------------------------------------------------------------------


async def _handle_sandbox_forward(
    message: Message,
    bot: Bot,
    session: MenuSession,
    sandbox: SandboxService | None,
    sessions: MenuSessionStore,
) -> None:
    def _restart() -> None:
        # Keep the wizard alive: on invalid input the "reintenta" hint must be
        # real, so the next forwarded message still lands here (A2).
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "sandbox_forward",
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    chat_id = _extract_chat_id_from_forward(message)
    if chat_id is None:
        _restart()
        await _edit_or_answer(
            bot,
            "No se pudo extraer el ID del chat del mensaje reenviado. "
            "Asegúrate de reenviar un mensaje del chat que quieres activar.\n\n"
            "Usa /cancelar para abortar.",
            session=session,
            fallback=message,
        )
        return

    if sandbox is None:
        _restart()
        await _edit_or_answer(
            bot,
            "El modo de prueba no está disponible.",
            session=session,
            fallback=message,
        )
        return

    profiles = sandbox.list_profiles()
    owner_id = message.from_user.id  # type: ignore[union-attr]
    text = f"Chat detectado: {chat_id}\n\nSelecciona el perfil de prueba:"
    kb = menu_sandbox_profile_picker_keyboard(profiles)
    sessions.start(
        owner_id,
        "sandbox_profile",
        sandbox_chat_id=chat_id,
        last_bot_message_id=session.last_bot_message_id,
        last_chat_id=session.last_chat_id,
    )
    await _edit_or_answer(
        bot, text, session=session, fallback=message, keyboard=kb,
    )


async def _handle_register_forward(
    message: Message,
    bot: Bot,
    session: MenuSession,
    vips: VipStore,
    sessions: MenuSessionStore,
) -> None:
    def _restart() -> None:
        # Keep the wizard alive: the "reenvia" hint must be real, so a bad
        # forward lets the owner try another message instead of restarting (A2).
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "register_vip",
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    user_info = _extract_user_from_forward(message)
    if user_info is None:
        _restart()
        await _edit_or_answer(
            bot,
            "No se pudo identificar al usuario. Asegúrate de reenviar "
            "un mensaje desde el chat de la persona que quieras agregar.\n\n"
            "Usa /cancelar para abortar.",
            session=session,
            fallback=message,
        )
        return

    user_id, display_name = user_info
    name_str = display_name or str(user_id)

    # Check if already an active VIP.
    existing = await vips.get_by_telegram_user_id(user_id)
    if existing is not None and existing.is_active:
        _restart()
        await _edit_or_answer(
            bot,
            f"El usuario {name_str} (ID: {user_id}) ya es un VIP activo. "
            "Reenvía un mensaje de otra persona o usa /cancelar.",
            session=session,
            fallback=message,
        )
        return

    # Store the display name so the confirm handler can save it.
    if display_name is not None and message.from_user is not None:
        sessions.store_pending_vip_name(message.from_user.id, display_name)

    # Build confirmation text.
    text = (
        f"📋 Datos del usuario:\n"
        f"  ID: {user_id}\n"
        f"  Nombre: {display_name or '(sin nombre)'}\n"
    )
    if existing is not None and not existing.is_active:
        text += "\n⚠️ Este usuario estaba desactivado. Se reactivará."
    text += "\n¿Agregar este usuario como VIP?"

    # A7: start the confirmation TTL so a stale Confirm tap is rejected.
    if message.from_user is not None:
        sessions.record_confirmation(message.from_user.id)
    kb = menu_register_confirm_keyboard(user_id)
    await _edit_or_answer(
        bot, text, session=session, fallback=message, keyboard=kb,
    )


async def _handle_note_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    profile_admin: ProfileAdminService | None,
    sessions: MenuSessionStore,
) -> None:
    def _restart() -> None:
        # Keep the note wizard alive on validation/service errors so the owner
        # can retry the same prompt (A2) instead of silently dropping it.
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "note",
            vip_user_id=session.vip_user_id,
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    back_kb = (
        menu_back_keyboard(encode_menu_vip(session.vip_user_id))
        if session.vip_user_id
        else None
    )
    if profile_admin is None or session.vip_user_id is None:
        await _edit_or_answer(
            bot, "Gestión de notas no disponible.",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    text = (message.text or "").strip()
    if not text:
        _restart()
        await _edit_or_answer(
            bot, "El texto de la nota no puede estar vacío. "
            "Envíalo de nuevo o usa /cancelar.",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    result = await profile_admin.add_note(
        message.from_user.id,  # type: ignore[union-attr]
        session.vip_user_id,
        text,
    )
    name = result.display_name or str(session.vip_user_id)
    if result.status == "note_added":
        await _edit_or_answer(
            bot, f"Nota agregada a {name}.",
            session=session, fallback=message, keyboard=back_kb,
        )
    else:
        _restart()
        await _edit_or_answer(
            bot, f"No se pudo agregar la nota: {result.status}. "
            "Reinténtalo o usa /cancelar.",
            session=session, fallback=message, keyboard=back_kb,
        )


async def _handle_fact_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    profile_admin: ProfileAdminService | None,
    sessions: MenuSessionStore,
) -> None:
    def _restart() -> None:
        # Keep the fact wizard alive on validation/service errors (A2).
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "fact",
            vip_user_id=session.vip_user_id,
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    back_kb = (
        menu_back_keyboard(encode_menu_vip(session.vip_user_id))
        if session.vip_user_id
        else None
    )
    if profile_admin is None or session.vip_user_id is None:
        await _edit_or_answer(
            bot, "Gestión de perfiles no disponible.",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    text = (message.text or "").strip()
    if ":" not in text:
        _restart()
        await _edit_or_answer(
            bot, "Formato incorrecto. Usa:\nclave: valor\n\n"
            "Usa /cancelar para abortar.",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    key, _, value = text.partition(":")
    key = key.strip()
    value = value.strip()
    if not key or not value:
        _restart()
        await _edit_or_answer(
            bot, "La clave y el valor no pueden estar vacíos.\n\n"
            "Usa /cancelar para abortar.",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    result = await profile_admin.set_fact(
        message.from_user.id,  # type: ignore[union-attr]
        session.vip_user_id,
        key,
        value,
    )
    name = result.display_name or str(session.vip_user_id)
    if result.status == "fact_set":
        await _edit_or_answer(
            bot, f"Dato '{key}' agregado a {name}.",
            session=session, fallback=message, keyboard=back_kb,
        )
    else:
        _restart()
        await _edit_or_answer(
            bot, f"No se pudo agregar el dato: {result.status}. "
            "Reinténtalo o usa /cancelar.",
            session=session, fallback=message, keyboard=back_kb,
        )


async def _handle_rename_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    vips: VipStore,
    sessions: MenuSessionStore,
) -> None:
    def _restart() -> None:
        # Keep the rename wizard alive on validation errors (A2).
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "rename",
            vip_user_id=session.vip_user_id,
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    if session.vip_user_id is None:
        return
    back_kb = menu_back_keyboard(encode_menu_vip(session.vip_user_id))
    new_name = (message.text or "").strip()
    if not new_name:
        _restart()
        await _edit_or_answer(
            bot, "El nombre no puede estar vacío. "
            "Escríbelo de nuevo o usa /cancelar.",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    result = await vips.rename(session.vip_user_id, new_name)
    if result is not None:
        await _edit_or_answer(
            bot, f"VIP renombrado a '{new_name}'.",
            session=session, fallback=message, keyboard=back_kb,
        )
    else:
        _restart()
        await _edit_or_answer(
            bot,
            f"No se encontró al VIP {session.vip_user_id} o está inactivo. "
            "Reinténtalo o usa /cancelar.",
            session=session, fallback=message, keyboard=back_kb,
        )


# ---------------------------------------------------------------------------
# Eventos temporales — list/detail renderers, action dispatch, wizard steps
# ---------------------------------------------------------------------------

_EVENT_DURATION_ACTIONS = ("dur_today", "dur_2d", "dur_3d", "dur_1w")
_EVENT_DURATION_TEXT = {
    "dur_today": "hoy",
    "dur_2d": "2 días",
    "dur_3d": "3 días",
    "dur_1w": "1 semana",
}


def _format_event_dt(dt: datetime) -> str:
    """Short server-local datetime for the owner (dd/mm/yyyy HH:MM)."""
    return dt.astimezone().strftime("%d/%m/%Y %H:%M")


def _event_detail_text(record: EphemeralEventRecord) -> str:
    """Body, pause state and window for the event detail card."""
    status = "⏸️ Pausado" if record.is_paused else "🟢 Activo"
    return (
        f"📅 {record.body}\n\n"
        f"Estado: {status}\n"
        f"🕐 Desde: {_format_event_dt(record.start_at)}\n"
        f"🕐 Hasta: {_format_event_dt(record.end_at)}\n\n"
        "Selecciona una acción:"
    )


async def _render_event_list(
    message: Message,
    service: EphemeralEventService | None,
    actor_id: int,
) -> None:
    """Render the open-events list, editing the current message in place."""
    if service is None:
        await _show(
            message,
            "Los eventos temporales no están disponibles.",
            menu_back_keyboard(encode_menu("event")),
        )
        return
    events = await service.list_open(actor_id)
    if not events:
        await _show(message, MENU_EVENT_EMPTY_TEXT, menu_event_list_keyboard([]))
        return
    await _show(message, MENU_EVENT_LIST_TEXT, menu_event_list_keyboard(events))


async def _render_event_detail(message: Message, record: EphemeralEventRecord) -> None:
    await _show(message, _event_detail_text(record), menu_event_detail_keyboard(record))


async def _update_event(
    service: EphemeralEventService,
    actor_id: int,
    event_id: UUID,
    *,
    body: str,
    start_at: datetime,
    end_at: datetime,
) -> EphemeralEventRecord | None:
    """Edit an event in place (preserves id and pause state)."""
    return await service.update(
        actor_id, event_id, body=body, start_at=start_at, end_at=end_at
    )


async def _apply_duration_selection(
    message: Message,
    service: EphemeralEventService,
    actor_id: int,
    sessions: MenuSessionStore,
    *,
    event_id: UUID | None,
    duration_action: str,
) -> None:
    """Compute the window from a quick-duration tap and continue the flow.

    Create mode (``event_id is None``) stores the window in the session and
    shows the confirmation; edit mode applies the change immediately.
    """
    now = datetime.now(UTC)
    try:
        end_at = service.parse_relative_or_absolute(
            _EVENT_DURATION_TEXT[duration_action], now
        )
    except ValueError:
        await _show(
            message, "Duración no válida.", menu_back_keyboard(encode_menu("event"))
        )
        return

    if event_id is not None:
        # Edit mode: update the window in place, preserving pause state.
        record = await service.get(actor_id, event_id)
        if record is None:
            await _show(
                message, "El evento ya no existe.",
                menu_back_keyboard(encode_menu("event")),
            )
            return
        updated = await _update_event(
            service, actor_id, event_id,
            body=record.body, start_at=now, end_at=end_at,
        )
        if updated is None:
            await _show(
                message, "No se pudo modificar el evento.",
                menu_back_keyboard(encode_menu("event")),
            )
            return
        await _render_event_detail(message, updated)
        return

    # Create mode: keep the body/window in the session for the confirmation.
    session = sessions.get(actor_id)
    body = session.event_body if session else None
    if not body:
        await _show(
            message, _SESSION_EXPIRED_UX, menu_back_keyboard(encode_menu("event"))
        )
        return
    sessions.start(
        actor_id,
        "event_duration",
        event_body=body,
        event_start_at=now,
        event_end_at=end_at,
        last_bot_message_id=message.message_id,
        last_chat_id=message.chat.id,
    )
    await _show(
        message,
        MENU_EVENT_CONFIRM_TEMPLATE.format(
            body=body,
            start=_format_event_dt(now),
            end=_format_event_dt(end_at),
        ),
        menu_event_confirm_keyboard(),
    )


async def _dispatch_event_action(
    message: Message,
    *,
    parsed: MenuCallback,
    actor_id: int,
    service: EphemeralEventService | None,
    sessions: MenuSessionStore,
) -> None:
    """Dispatch m:event:* callbacks (detail, per-event actions, create wizard).

    Returns ``"confirm_expired"`` when a stale destructive-confirm button is
    tapped (mirrors the VIP delete flow), so the caller can alert the owner.
    """
    event_id = parsed.event_id
    action = parsed.action

    if service is None:
        await _show(
            message,
            "Los eventos temporales no están disponibles.",
            menu_back_keyboard(encode_menu("event")),
        )
        return

    # --- detail (m:event:<uuid>) ---
    if event_id is not None and action is None:
        record = await service.get(actor_id, event_id)
        if record is None:
            await _show(
                message, "El evento ya no existe.",
                menu_back_keyboard(encode_menu("event")),
            )
            return
        await _render_event_detail(message, record)
        return

    # --- per-event actions ---
    if event_id is not None:
        if action in ("pause", "resume"):
            await service.set_paused(actor_id, event_id, action == "pause")
            record = await service.get(actor_id, event_id)
            if record is None:
                await _show(
                    message, "El evento ya no existe.",
                    menu_back_keyboard(encode_menu("event")),
                )
                return
            await _render_event_detail(message, record)
            return

        if action == "terminate":
            sessions.record_confirmation(actor_id)
            await _show(
                message,
                "🛑 ¿Terminar este evento antes de tiempo?\n\n"
                "Diana dejará de verlo de inmediato.",
                menu_event_terminate_confirm_keyboard(event_id),
            )
            return

        if action == "terminate_confirm":
            if not sessions.consume_confirmation(actor_id):
                await _show(
                    message, _CONFIRM_EXPIRED_UX,
                    menu_back_keyboard(encode_menu("event")),
                )
                return "confirm_expired"
            await service.terminate(actor_id, event_id)
            await _render_event_list(message, service, actor_id)
            return

        if action == "delete":
            sessions.record_confirmation(actor_id)
            await _show(
                message,
                "🗑️ ¿Eliminar este evento?\n\n"
                "Se quitará de forma definitiva.",
                menu_event_confirm_delete_keyboard(event_id),
            )
            return

        if action == "delete_confirm":
            if not sessions.consume_confirmation(actor_id):
                await _show(
                    message, _CONFIRM_EXPIRED_UX,
                    menu_back_keyboard(encode_menu("event")),
                )
                return "confirm_expired"
            await service.delete(actor_id, event_id)
            await _render_event_list(message, service, actor_id)
            return

        if action == "modify":
            record = await service.get(actor_id, event_id)
            if record is None:
                await _show(
                    message, "El evento ya no existe.",
                    menu_back_keyboard(encode_menu("event")),
                )
                return
            await _show(
                message, "✏️ Modificar evento\n\n¿Qué quieres cambiar?",
                menu_event_modify_keyboard(event_id),
            )
            return

        if action == "edit_text":
            sessions.start(
                actor_id,
                "event_edit_body",
                event_id=event_id,
                last_bot_message_id=message.message_id,
                last_chat_id=message.chat.id,
            )
            await _show(message, MENU_EVENT_EDIT_BODY_PROMPT, None)
            return

        if action == "edit_duration":
            await _show(
                message,
                MENU_EVENT_EDIT_DURATION_PROMPT,
                menu_event_duration_keyboard(event_id),
            )
            return

        if action in _EVENT_DURATION_ACTIONS:
            await _apply_duration_selection(
                message, service, actor_id, sessions,
                event_id=event_id, duration_action=action,
            )
            return

        if action == "dur_custom":
            sessions.start(
                actor_id,
                "event_custom_start",
                event_id=event_id,
                last_bot_message_id=message.message_id,
                last_chat_id=message.chat.id,
            )
            await _show(message, MENU_EVENT_CUSTOM_START_PROMPT, None)
            return

        await _show(
            message, "Acción no disponible.", menu_back_keyboard(encode_menu("event"))
        )
        return

    # --- create-mode actions (no event yet) ---
    if action == "create":
        sessions.start(
            actor_id,
            "event_body",
            last_bot_message_id=message.message_id,
            last_chat_id=message.chat.id,
        )
        await _show(message, MENU_EVENT_CREATE_BODY_PROMPT, None)
        return

    if action == "create_cancel":
        sessions.cancel(actor_id)
        await _render_event_list(message, service, actor_id)
        return

    if action == "create_confirm":
        session = sessions.get(actor_id)
        if (
            session is None
            or not session.event_body
            or session.event_start_at is None
            or session.event_end_at is None
        ):
            await _show(
                message, _SESSION_EXPIRED_UX, menu_back_keyboard(encode_menu("event"))
            )
            return
        await service.create(
            actor_id,
            body=session.event_body,
            start_at=session.event_start_at,
            end_at=session.event_end_at,
        )
        sessions.cancel(actor_id)
        await _render_event_list(message, service, actor_id)
        return

    if action in _EVENT_DURATION_ACTIONS:
        await _apply_duration_selection(
            message, service, actor_id, sessions,
            event_id=None, duration_action=action,
        )
        return

    if action == "dur_custom":
        sessions.start(
            actor_id,
            "event_custom_start",
            last_bot_message_id=message.message_id,
            last_chat_id=message.chat.id,
        )
        await _show(message, MENU_EVENT_CUSTOM_START_PROMPT, None)
        return

    await _show(
        message, "Acción no disponible.", menu_back_keyboard(encode_menu("event"))
    )


async def _handle_event_body_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    service: EphemeralEventService | None,
    sessions: MenuSessionStore,
) -> None:
    """Create wizard step 1: capture the body, then show the duration picker."""

    def _restart() -> None:
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "event_body",
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    if service is None:
        await _edit_or_answer(
            bot,
            "Los eventos temporales no están disponibles.",
            session=session, fallback=message,
            keyboard=menu_back_keyboard(encode_menu("event")),
        )
        return
    body = (message.text or "").strip()
    if not body:
        _restart()
        await _edit_or_answer(
            bot,
            "El texto del evento no puede estar vacío. Escríbelo de nuevo o usa /cancelar.",
            session=session, fallback=message,
        )
        return
    sessions.start(
        message.from_user.id,  # type: ignore[union-attr]
        "event_duration",
        event_body=body,
        last_bot_message_id=session.last_bot_message_id,
        last_chat_id=session.last_chat_id,
    )
    await _edit_or_answer(
        bot, MENU_EVENT_DURATION_PROMPT, session=session, fallback=message,
        keyboard=menu_event_duration_keyboard(),
    )


async def _handle_event_custom_start_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    service: EphemeralEventService | None,
    sessions: MenuSessionStore,
) -> None:
    """Custom-date step 1: parse the start datetime, then ask for the end."""

    def _restart() -> None:
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "event_custom_start",
            event_body=session.event_body,
            event_id=session.event_id,
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    if service is None:
        await _edit_or_answer(
            bot,
            "Los eventos temporales no están disponibles.",
            session=session, fallback=message,
            keyboard=menu_back_keyboard(encode_menu("event")),
        )
        return
    text = (message.text or "").strip()
    now = datetime.now(UTC)
    try:
        start_at = now if text.lower() == "ahora" else service.parse_relative_or_absolute(text, now)
    except ValueError as exc:
        _restart()
        await _edit_or_answer(bot, str(exc), session=session, fallback=message)
        return
    sessions.start(
        message.from_user.id,  # type: ignore[union-attr]
        "event_custom_end",
        event_body=session.event_body,
        event_start_at=start_at,
        event_id=session.event_id,
        last_bot_message_id=session.last_bot_message_id,
        last_chat_id=session.last_chat_id,
    )
    await _edit_or_answer(
        bot, MENU_EVENT_CUSTOM_END_PROMPT, session=session, fallback=message,
    )


async def _handle_event_custom_end_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    service: EphemeralEventService | None,
    sessions: MenuSessionStore,
) -> None:
    """Custom-date step 2: parse the end (relative to the start) and finish."""

    def _restart() -> None:
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "event_custom_end",
            event_body=session.event_body,
            event_start_at=session.event_start_at,
            event_id=session.event_id,
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    actor_id = message.from_user.id  # type: ignore[union-attr]
    if service is None:
        await _edit_or_answer(
            bot,
            "Los eventos temporales no están disponibles.",
            session=session, fallback=message,
            keyboard=menu_back_keyboard(encode_menu("event")),
        )
        return
    if session.event_start_at is None:
        _restart()
        await _edit_or_answer(
            bot,
            "No se encontró la fecha de inicio. Vuelve a empezar o usa /cancelar.",
            session=session, fallback=message,
        )
        return
    text = (message.text or "").strip()
    try:
        end_at = service.parse_relative_or_absolute(text, session.event_start_at)
    except ValueError as exc:
        _restart()
        await _edit_or_answer(bot, str(exc), session=session, fallback=message)
        return

    if session.event_id is not None:
        # Edit mode: update the window in place, preserving pause state.
        record = await service.get(actor_id, session.event_id)
        if record is None:
            await _edit_or_answer(
                bot, "El evento ya no existe.",
                session=session, fallback=message,
                keyboard=menu_back_keyboard(encode_menu("event")),
            )
            return
        updated = await _update_event(
            service, actor_id, session.event_id,
            body=record.body,
            start_at=session.event_start_at,
            end_at=end_at,
        )
        sessions.cancel(actor_id)
        await _edit_or_answer(
            bot, _event_detail_text(updated),
            session=session, fallback=message,
            keyboard=menu_event_detail_keyboard(updated),
        )
        return

    # Create mode: keep the body/window in the session for the confirmation.
    sessions.start(
        message.from_user.id,  # type: ignore[union-attr]
        "event_duration",
        event_body=session.event_body,
        event_start_at=session.event_start_at,
        event_end_at=end_at,
        last_bot_message_id=session.last_bot_message_id,
        last_chat_id=session.last_chat_id,
    )
    await _edit_or_answer(
        bot,
        MENU_EVENT_CONFIRM_TEMPLATE.format(
            body=session.event_body,
            start=_format_event_dt(session.event_start_at),
            end=_format_event_dt(end_at),
        ),
        session=session, fallback=message,
        keyboard=menu_event_confirm_keyboard(),
    )


async def _handle_event_edit_body_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    service: EphemeralEventService | None,
    sessions: MenuSessionStore,
) -> None:
    """Modify wizard: capture the new body and apply the edit in place."""

    def _restart() -> None:
        sessions.start(
            message.from_user.id,  # type: ignore[union-attr]
            "event_edit_body",
            event_id=session.event_id,
            last_bot_message_id=session.last_bot_message_id,
            last_chat_id=session.last_chat_id,
        )

    actor_id = message.from_user.id  # type: ignore[union-attr]
    if service is None or session.event_id is None:
        await _edit_or_answer(
            bot,
            "Los eventos temporales no están disponibles.",
            session=session, fallback=message,
            keyboard=menu_back_keyboard(encode_menu("event")),
        )
        return
    new_body = (message.text or "").strip()
    if not new_body:
        _restart()
        await _edit_or_answer(
            bot,
            "El texto del evento no puede estar vacío. Escríbelo de nuevo o usa /cancelar.",
            session=session, fallback=message,
        )
        return
    record = await service.get(actor_id, session.event_id)
    if record is None:
        await _edit_or_answer(
            bot, "El evento ya no existe.",
            session=session, fallback=message,
            keyboard=menu_back_keyboard(encode_menu("event")),
        )
        return
    updated = await _update_event(
        service, actor_id, session.event_id,
        body=new_body, start_at=record.start_at, end_at=record.end_at,
    )
    sessions.cancel(actor_id)
    await _edit_or_answer(
        bot, _event_detail_text(updated),
        session=session, fallback=message,
        keyboard=menu_event_detail_keyboard(updated),
    )


__all__ = [
    "HasActiveMenuSession",
    "MenuSession",
    "MenuSessionStore",
    "build_menu_router",
]
