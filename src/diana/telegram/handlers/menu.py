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

from aiogram import Bot, Router
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, Message

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_trace_service import AdminTraceService
from diana.application.ports import VipStore
from diana.application.profile_admin_service import ProfileAdminService
from diana.application.sandbox import SandboxService
from diana.application.staging_service import StagingService
from diana.application.turn_coordinator import TurnCoordinator
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
    MENU_ROOT_TEXT,
    MenuCallback,
    encode_menu,
    encode_menu_vip,
    menu_back_keyboard,
    menu_confirm_delete_keyboard,
    menu_freeze_duration_keyboard,
    menu_history_keyboard,
    menu_metrics_keyboard,
    menu_register_confirm_keyboard,
    menu_review_keyboard,
    menu_root_keyboard,
    menu_sandbox_keyboard,
    menu_sandbox_profile_picker_keyboard,
    menu_vip_detail_keyboard,
    menu_vip_list_keyboard,
    menu_vip_profile_keyboard,
    metrics_keyboard,
    parse_menu_callback,
    staging_candidate_keyboard,
    trace_list_keyboard,
)

logger = logging.getLogger("diana.telegram")

# ---------------------------------------------------------------------------
# MenuSessionStore — process-local FSM for multi-step menu flows
# ---------------------------------------------------------------------------

DEFAULT_MENU_TTL = timedelta(minutes=15)

MenuSessionKind = Literal[
    "sandbox_forward", "sandbox_profile", "note", "fact", "rename", "register_vip"
]


@dataclass
class MenuSession:
    """A single in-progress multi-step menu operation."""

    kind: MenuSessionKind
    vip_user_id: int | None = None
    sandbox_chat_id: int | None = None
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
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(UTC))

    def start(self, owner_id: int, kind: MenuSessionKind, **kwargs: Any) -> None:
        self._sessions[owner_id] = MenuSession(kind=kind, **kwargs)

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

    def cancel(self, owner_id: int) -> None:
        self._sessions.pop(owner_id, None)


class HasActiveMenuSession(Filter):
    """Aiogram filter: True when the owner has a live MenuSession."""

    def __init__(self, sessions: MenuSessionStore) -> None:
        self.sessions = sessions

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None:
            return False
        return self.sessions.has_active(message.from_user.id)


# ---------------------------------------------------------------------------
# Category keyboards — "vips" is dynamic, rest are static
# ---------------------------------------------------------------------------

_CATEGORY_KEYBOARDS: dict[str, Any] = {
    "vips": None,  # dynamic — needs VIP list from DB
    "review": menu_review_keyboard,
    "sandbox": menu_sandbox_keyboard,
    "metrics": menu_metrics_keyboard,
    "history": menu_history_keyboard,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_vip_profile(result: Any) -> str:
    """Format a ``ProfileAdminResult`` for display."""
    if result.status == "vip_not_found":
        return "VIP no encontrado."
    if result.status == "profile_empty":
        name = result.display_name or str(result.telegram_user_id)
        return f"Ficha de {name}\n\nSin datos todavia."

    name = result.display_name or str(result.telegram_user_id)
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


# ---------------------------------------------------------------------------
# build_menu_router
# ---------------------------------------------------------------------------


def build_menu_router(
    *,
    owner_telegram_id: int,
    vips: VipStore,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    sandbox: SandboxService | None = None,
    staging: StagingService | None = None,
    coordinator: TurnCoordinator | None = None,
    profile_admin: ProfileAdminService | None = None,
    menu_sessions: MenuSessionStore | None = None,
) -> Router:
    """Build the router serving /start, /menu, m:* callbacks, and menu-session text."""
    router = Router(name="menu")
    sessions = menu_sessions or MenuSessionStore()

    def _is_owner(message: Message) -> bool:
        return is_private_owner_message(message, owner_telegram_id)

    # ---- /start, /menu ----

    @router.message(Command("start", "menu"))
    async def on_menu(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        await message.answer(MENU_ROOT_TEXT, reply_markup=menu_root_keyboard())

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
                await _show(callback.message, MENU_ROOT_TEXT, menu_root_keyboard())
            return

        msg = callback.message
        if not isinstance(msg, Message):
            return

        # --- category submenu (action is None) ---
        if parsed.action is None and parsed.category != "vip":
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

            build_kb = _CATEGORY_KEYBOARDS.get(parsed.category)
            text = MENU_CATEGORY_TEXT.get(parsed.category)
            if build_kb is None or text is None:
                return
            await _show(msg, text, build_kb())
            return

        # --- dispatch concrete actions ---
        await _dispatch_action(
            msg,
            parsed=parsed,
            actor_id=actor_id,
            vips=vips,
            admin_trace=admin_trace,
            admin_metrics=admin_metrics,
            sandbox=sandbox,
            staging=staging,
            coordinator=coordinator,
            profile_admin=profile_admin,
            sessions=sessions,
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
            await message.reply("No hay ninguna operacion activa para cancelar.")

    @router.message(HasActiveMenuSession(sessions))
    async def on_menu_session_text(message: Message, bot: Bot, **_: Any) -> None:
        if not _is_owner(message):
            return
        owner_id = message.from_user.id  # type: ignore[union-attr]

        # Treat literal "/cancelar" as a cancel command, not as input text,
        # so users who follow the "Usa /cancelar para abortar." instruction
        # don't accidentally rename the VIP (or add a note/fact) to "/cancelar".
        text = (message.text or "").strip()
        if text == "/cancelar":
            sessions.pop(owner_id)
            await message.reply("Operacion cancelada.")
            return

        session = sessions.pop(owner_id)
        if session is None:
            return

        if session.kind == "sandbox_forward":
            await _handle_sandbox_forward(message, bot, session, sandbox, sessions)
        elif session.kind == "sandbox_profile":
            await _edit_or_answer(
                bot, "Usa los botones para seleccionar un perfil.",
                session=session, fallback=message,
            )
        elif session.kind == "register_vip":
            await _handle_register_forward(message, bot, session, vips, sessions)
        elif session.kind == "note":
            await _handle_note_text(message, bot, session, profile_admin)
        elif session.kind == "fact":
            await _handle_fact_text(message, bot, session, profile_admin)
        elif session.kind == "rename":
            await _handle_rename_text(message, bot, session, vips)

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
    sandbox: SandboxService | None,
    staging: StagingService | None,
    coordinator: TurnCoordinator | None,
    profile_admin: ProfileAdminService | None,
    sessions: MenuSessionStore,
) -> None:
    category = parsed.category
    action = parsed.action

    # ==================================================================
    # VIP detail & per-VIP actions
    # ==================================================================
    if category == "vip" and parsed.vip_user_id is not None:
        user_id = parsed.vip_user_id

        # Show VIP detail card
        if action == str(user_id):
            vip = await vips.get_by_telegram_user_id(user_id)
            name = vip.display_name if vip and vip.display_name else str(user_id)
            is_frozen = bool(
                vip and vip.frozen_until and vip.frozen_until > datetime.now(UTC)
            )
            status_line = "Estado: 🔒 Pausado\n" if is_frozen else "Estado: 🟢 Activo\n"
            text = (
                f"👤 Perfil de {name}\n"
                f"ID: {user_id}\n\n"
                f"{status_line}"
                "Selecciona una accion:"
            )
            await _show(message, text, menu_vip_detail_keyboard(user_id, is_frozen=is_frozen))
            return

        # --- profile (view ficha) ---
        if action == "profile":
            if profile_admin is None:
                await _show(message, "Gestion de perfiles no disponible.", None)
                return
            result = await profile_admin.show_profile(actor_id, user_id)
            await _show(
                message,
                _format_vip_profile(result),
                menu_vip_profile_keyboard(user_id),
            )
            return

        # --- add note ---
        if action == "note_add":
            if profile_admin is None:
                await _show(message, "Gestion de perfiles no disponible.", None)
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
                await _show(message, "Gestion de perfiles no disponible.", None)
                return
            try:
                idx = int(parsed.extra or "0")
            except ValueError:
                await _show(message, "Numero de nota invalido.", None)
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
                await _show(message, "Gestion de perfiles no disponible.", None)
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
                await _show(message, "Gestion de perfiles no disponible.", None)
                return
            key = (parsed.extra or "").strip()
            if not key:
                await _show(message, "Especifica la clave del dato a eliminar.", None)
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
            await _show(
                message,
                f"¿Desactivar al VIP {user_id}?\n\n"
                "Se desactivara, no se borrara permanentemente.",
                menu_confirm_delete_keyboard(user_id),
            )
            return

        # --- delete confirmed ---
        if action == "delete_confirm":
            ok = await vips.deactivate(user_id)
            kb = menu_back_keyboard(encode_menu("vips"))
            if ok:
                await _show(message, f"VIP {user_id} desactivado.", kb)
            else:
                await _show(message, f"No se encontro al VIP {user_id}.", kb)
            return

        # --- freeze (pausar) ---
        if action == "freeze":
            duration = parsed.extra
            # No duration yet — show the duration picker submenu
            if duration is None:
                vip = await vips.get_by_telegram_user_id(user_id)
                name = vip.display_name if vip and vip.display_name else str(user_id)
                await _show(
                    message,
                    f"⏸ Pausar a {name}\n\n"
                    "Elegi la duracion de la pausa:",
                    menu_freeze_duration_keyboard(user_id),
                )
                return

            vip = await vips.get_by_telegram_user_id(user_id)
            if vip is None or not vip.is_active:
                await _show(message, f"VIP {user_id} no encontrado o inactivo.", None)
                return

            now = datetime.now(UTC)
            if duration == "1d":
                frozen_until = now + timedelta(days=1)
            elif duration == "7d":
                frozen_until = now + timedelta(days=7)
            else:
                frozen_until = datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC)

            await vips.freeze_vip(vip.id, frozen_until)

            vip = await vips.get_by_telegram_user_id(user_id)
            is_frozen = bool(
                vip and vip.frozen_until and vip.frozen_until > datetime.now(UTC)
            )
            name = vip.display_name if vip and vip.display_name else str(user_id)
            status_line = "Estado: 🔒 Pausado\n" if is_frozen else "Estado: 🟢 Activo\n"
            text = (
                f"👤 Perfil de {name}\n"
                f"ID: {user_id}\n\n"
                f"{status_line}"
                "Selecciona una accion:"
            )
            await _show(
                message, text, menu_vip_detail_keyboard(user_id, is_frozen=is_frozen)
            )
            return

        # --- unfreeze (reanudar) ---
        if action == "unfreeze":
            vip = await vips.get_by_telegram_user_id(user_id)
            if vip is None or not vip.is_active:
                await _show(message, f"VIP {user_id} no encontrado o inactivo.", None)
                return
            await vips.unfreeze_vip(vip.id)
            # Re-query to get updated state
            vip = await vips.get_by_telegram_user_id(user_id)
            name = vip.display_name if vip and vip.display_name else str(user_id)
            text = (
                f"👤 Perfil de {name}\n"
                f"ID: {user_id}\n\n"
                "Estado: 🟢 Activo\n"
                "Selecciona una accion:"
            )
            await _show(
                message, text, menu_vip_detail_keyboard(user_id, is_frozen=False)
            )
            return

        await _show(message, "Accion no disponible.", None)
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
            try:
                user_id = int(parsed.extra or "0")
            except (ValueError, TypeError):
                await _show(message, "ID de usuario inválido.", None)
                return

            # Check if already exists (active or not)
            existing = await vips.get_by_telegram_user_id(user_id)
            display_name: str | None = None
            if existing is not None:
                display_name = existing.display_name

            result = await vips.add(user_id)
            name = display_name or result.display_name or str(user_id)
            await _show(
                message,
                f"✅ VIP registrado: {name} (ID: {user_id})",
                menu_back_keyboard(encode_menu("vips")),
            )
            return

        await _show(message, "Acción no disponible.", None)
        return

    # ==================================================================
    # Sandbox
    # ==================================================================
    if category == "sandbox":
        if sandbox is None:
            await _show(message, "El modo de prueba no esta disponible.", None)
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
                "Para activar el modo de prueba, reenvia un mensaje del chat "
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
                    "No se encontro el chat. Inicia de nuevo la activacion.",
                    None,
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
                await _show(message, "No hay modo de prueba activo.", None)
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
                await _show(message, "No hay modo de prueba activo.", None)
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
                f"Conversacion de prueba reiniciada (chat {focus}).",
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
            "Usalo cuando Diana escalo algo que en realidad no era un problema.\n"
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
                    "Error del sistema al cargar metricas. Reintenta mas tarde.",
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
                    "El aprendizaje por ejemplos no esta disponible.",
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
            await _show(message, "El historial no esta disponible.", back)
            return
        try:
            view = await admin_trace.render_turns_page(0)
        except Exception:
            logger.exception("Error querying traces")
            await _show(
                message,
                "Error del sistema al consultar el historial. Reintenta mas tarde.",
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

    # Unknown / unmapped action — should not normally happen.
    await _show(
        message,
        "Esa opcion todavia no esta disponible.",
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
    chat_id = _extract_chat_id_from_forward(message)
    if chat_id is None:
        await _edit_or_answer(
            bot,
            "No se pudo extraer el ID del chat del mensaje reenviado. "
            "Asegurate de reenviar un mensaje del chat que quieres activar.",
            session=session,
            fallback=message,
        )
        return

    if sandbox is None:
        await _edit_or_answer(
            bot,
            "El modo de prueba no esta disponible.",
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
    user_info = _extract_user_from_forward(message)
    if user_info is None:
        await _edit_or_answer(
            bot,
            "No se pudo identificar al usuario. Asegurate de reenviar "
            "un mensaje desde el chat de la persona que quieras agregar.",
            session=session,
            fallback=message,
        )
        return

    user_id, display_name = user_info
    name_str = display_name or str(user_id)

    # Check if already an active VIP.
    existing = await vips.get_by_telegram_user_id(user_id)
    if existing is not None and existing.is_active:
        await _edit_or_answer(
            bot,
            f"El usuario {name_str} (ID: {user_id}) ya es un VIP activo.",
            session=session,
            fallback=message,
        )
        return

    # Build confirmation text.
    text = (
        f"📋 Datos del usuario:\n"
        f"  ID: {user_id}\n"
        f"  Nombre: {display_name or '(sin nombre)'}\n"
    )
    if existing is not None and not existing.is_active:
        text += "\n⚠️ Este usuario estaba desactivado. Se reactivará."
    text += "\n¿Agregar este usuario como VIP?"

    kb = menu_register_confirm_keyboard(user_id)
    await _edit_or_answer(
        bot, text, session=session, fallback=message, keyboard=kb,
    )


async def _handle_note_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    profile_admin: ProfileAdminService | None,
) -> None:
    back_kb = (
        menu_back_keyboard(encode_menu_vip(session.vip_user_id))
        if session.vip_user_id
        else None
    )
    if profile_admin is None or session.vip_user_id is None:
        await _edit_or_answer(
            bot, "Gestion de perfiles no disponible.",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    text = (message.text or "").strip()
    if not text:
        await _edit_or_answer(
            bot, "El texto de la nota no puede estar vacio.",
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
        await _edit_or_answer(
            bot, f"No se pudo agregar la nota: {result.status}",
            session=session, fallback=message, keyboard=back_kb,
        )


async def _handle_fact_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    profile_admin: ProfileAdminService | None,
) -> None:
    back_kb = (
        menu_back_keyboard(encode_menu_vip(session.vip_user_id))
        if session.vip_user_id
        else None
    )
    if profile_admin is None or session.vip_user_id is None:
        await _edit_or_answer(
            bot, "Gestion de perfiles no disponible.",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    text = (message.text or "").strip()
    if ":" not in text:
        await _edit_or_answer(
            bot, "Formato incorrecto. Usa:\nclave: valor",
            session=session, fallback=message, keyboard=back_kb,
        )
        return
    key, _, value = text.partition(":")
    key = key.strip()
    value = value.strip()
    if not key or not value:
        await _edit_or_answer(
            bot, "La clave y el valor no pueden estar vacios.",
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
        await _edit_or_answer(
            bot, f"No se pudo agregar el dato: {result.status}",
            session=session, fallback=message, keyboard=back_kb,
        )


async def _handle_rename_text(
    message: Message,
    bot: Bot,
    session: MenuSession,
    vips: VipStore,
) -> None:
    if session.vip_user_id is None:
        return
    back_kb = menu_back_keyboard(encode_menu_vip(session.vip_user_id))
    new_name = (message.text or "").strip()
    if not new_name:
        await _edit_or_answer(
            bot, "El nombre no puede estar vacio.",
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
        await _edit_or_answer(
            bot,
            f"No se encontro al VIP {session.vip_user_id} o esta inactivo.",
            session=session, fallback=message, keyboard=back_kb,
        )


__all__ = [
    "HasActiveMenuSession",
    "MenuSession",
    "MenuSessionStore",
    "build_menu_router",
]
