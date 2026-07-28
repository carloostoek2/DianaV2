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

from aiogram import Router
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
    menu_confirm_delete_keyboard,
    menu_history_keyboard,
    menu_metrics_keyboard,
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
    "sandbox_forward", "sandbox_profile", "note", "fact", "rename"
]


@dataclass
class MenuSession:
    """A single in-progress multi-step menu operation."""

    kind: MenuSessionKind
    vip_user_id: int | None = None
    sandbox_chat_id: int | None = None
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

    @router.message(HasActiveMenuSession(sessions))
    async def on_menu_session_text(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        owner_id = message.from_user.id  # type: ignore[union-attr]
        session = sessions.pop(owner_id)
        if session is None:
            return

        if session.kind == "sandbox_forward":
            await _handle_sandbox_forward(message, sandbox, sessions)
        elif session.kind == "sandbox_profile":
            await message.answer("Usa los botones para seleccionar un perfil.")
        elif session.kind == "note":
            await _handle_note_text(message, session, profile_admin)
        elif session.kind == "fact":
            await _handle_fact_text(message, session, profile_admin)
        elif session.kind == "rename":
            await _handle_rename_text(message, session, vips)

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
            text = (
                f"👤 Perfil de {name}\n"
                f"ID: {user_id}\n\n"
                "Selecciona una accion:"
            )
            await _show(message, text, menu_vip_detail_keyboard(user_id))
            return

        # --- profile (view ficha) ---
        if action == "profile":
            if profile_admin is None:
                await message.answer("Gestion de perfiles no disponible.")
                return
            result = await profile_admin.show_profile(actor_id, user_id)
            await message.answer(
                _format_vip_profile(result),
                reply_markup=menu_vip_profile_keyboard(user_id),
            )
            return

        # --- add note ---
        if action == "note_add":
            if profile_admin is None:
                await message.answer("Gestion de perfiles no disponible.")
                return
            sessions.start(actor_id, "note", vip_user_id=user_id)
            await message.answer(
                f"Escribe la nota para el VIP {user_id}.\n\n"
                "Usa /cancelar para abortar."
            )
            return

        # --- delete note ---
        if action == "note_del":
            if profile_admin is None:
                await message.answer("Gestion de perfiles no disponible.")
                return
            try:
                idx = int(parsed.extra or "0")
            except ValueError:
                await message.answer("Numero de nota invalido.")
                return
            result = await profile_admin.delete_note(actor_id, user_id, idx)
            if result.status == "note_deleted":
                await message.answer(
                    f"Nota {idx} eliminada de {result.display_name or user_id}."
                )
            else:
                await message.answer(f"No se pudo eliminar la nota: {result.status}")
            return

        # --- add fact ---
        if action == "fact_add":
            if profile_admin is None:
                await message.answer("Gestion de perfiles no disponible.")
                return
            sessions.start(actor_id, "fact", vip_user_id=user_id)
            await message.answer(
                f"Escribe el dato para el VIP {user_id} en formato:\n"
                "clave: valor\n\n"
                "Usa /cancelar para abortar."
            )
            return

        # --- delete fact ---
        if action == "fact_del":
            if profile_admin is None:
                await message.answer("Gestion de perfiles no disponible.")
                return
            key = (parsed.extra or "").strip()
            if not key:
                await message.answer("Especifica la clave del dato a eliminar.")
                return
            result = await profile_admin.delete_fact(actor_id, user_id, key)
            if result.status == "fact_deleted":
                await message.answer(
                    f"Dato '{key}' eliminado de {result.display_name or user_id}."
                )
            else:
                await message.answer(f"No se pudo eliminar el dato: {result.status}")
            return

        # --- rename ---
        if action == "rename":
            sessions.start(actor_id, "rename", vip_user_id=user_id)
            await message.answer(
                f"Escribe el nuevo nombre para el VIP {user_id}.\n\n"
                "Usa /cancelar para abortar."
            )
            return

        # --- delete confirmation ---
        if action == "delete":
            await message.answer(
                f"¿Desactivar al VIP {user_id}?\n\n"
                "Se desactivara, no se borrara permanentemente.",
                reply_markup=menu_confirm_delete_keyboard(user_id),
            )
            return

        # --- delete confirmed ---
        if action == "delete_confirm":
            ok = await vips.deactivate(user_id)
            if ok:
                await message.answer(f"VIP {user_id} desactivado.")
            else:
                await message.answer(f"No se encontro al VIP {user_id}.")
            return

        await message.answer("Accion no disponible.")
        return

    # ==================================================================
    # Sandbox
    # ==================================================================
    if category == "sandbox":
        if sandbox is None:
            await message.answer("El modo de prueba no esta disponible.")
            return

        if action == "activate":
            sessions.start(actor_id, "sandbox_forward")
            await message.answer(
                "Para activar el modo de prueba, reenvia un mensaje del chat "
                "que quieres poner en modo sandbox.\n\n"
                "Usa /cancelar para abortar."
            )
            return

        if action == "activate_p":
            profile = parsed.extra or "nuevo"
            # Try to get the chat_id from a pending session
            session = sessions.get(actor_id)
            chat_id = session.sandbox_chat_id if session else None
            if chat_id is None:
                await message.answer(
                    "No se encontro el chat. Inicia de nuevo la activacion."
                )
                sessions.cancel(actor_id)
                return
            sessions.cancel(actor_id)
            sandbox.activate(chat_id, profile)
            await message.answer(
                f"Modo de prueba activado en chat {chat_id} con perfil '{profile}'."
            )
            return

        if action == "profiles":
            await message.answer(format_sandbox_perfiles(sandbox.list_profiles()))
            return

        if action == "status":
            await message.answer(sandbox.format_estado())
            return

        if action == "off":
            focus = sandbox.get_focus_chat_id()
            if focus is None:
                await message.answer("No hay modo de prueba activo.")
                return
            was = sandbox.deactivate(focus)
            await message.answer(
                f"Modo de prueba desactivado (chat {focus})."
                if was
                else "No habia modo de prueba activo."
            )
            return

        if action == "reset":
            focus = sandbox.get_focus_chat_id()
            if focus is None or not sandbox.is_active(focus):
                await message.answer("No hay modo de prueba activo.")
                return
            if coordinator is None:
                await message.answer(
                    "Error del sistema: no se puede reiniciar ahora."
                )
                return
            await coordinator.reset_chat_session(focus, reason="menu_reset")
            await message.answer(
                f"Conversacion de prueba reiniciada (chat {focus})."
            )
            return

        await message.answer("Accion no disponible.")
        return

    # ==================================================================
    # Review
    # ==================================================================
    if category == "review" and action == "fp":
        await message.answer(
            "Usa el comando:\n/fp <id_del_turno>\n\n"
            "Usalo cuando Diana escalo algo que en realidad no era un problema.\n"
            "El id del turno aparece en Historial -> Ver turnos recientes."
        )
        return

    # ==================================================================
    # Metrics
    # ==================================================================
    if category == "metrics":
        if action == "summary":
            if admin_metrics is None:
                await message.answer("Metricas no disponibles todavia.")
                return
            try:
                body, status = await admin_metrics.render_week_summary()
            except Exception:
                logger.exception("Error loading metrics summary")
                await message.answer(
                    "Error del sistema al cargar metricas. Reintenta mas tarde."
                )
                return
            kb = metrics_keyboard() if status == "ok" else None
            await message.answer(body, reply_markup=kb)
            return

        if action == "staging":
            token, rows = await load_pending_staging_list(staging=staging)
            if token == "unavailable":
                await message.answer(
                    "El aprendizaje por ejemplos no esta disponible."
                )
                return
            if token == "empty":
                await message.answer("No hay ejemplos pendientes de revision.")
                return
            for candidate in rows:
                await message.answer(
                    format_staging_candidate_body(candidate),
                    reply_markup=staging_candidate_keyboard(candidate.id),
                )
            return

    # ==================================================================
    # History
    # ==================================================================
    if category == "history" and action == "turns":
        if admin_trace is None:
            await message.answer("El historial no esta disponible.")
            return
        try:
            view = await admin_trace.render_turns_page(0)
        except Exception:
            logger.exception("Error querying traces")
            await message.answer(
                "Error del sistema al consultar el historial. Reintenta mas tarde."
            )
            return
        if view.empty:
            await message.answer("No hay turnos recientes.")
            return
        kb = trace_list_keyboard(
            view.turns_data, page=view.page, total_pages=view.total_pages
        )
        await message.answer(view.text, reply_markup=kb)
        return

    if category == "history" and action == "trace":
        await message.answer("Usa el comando:\n/traza <id_del_turno>")
        return

    # Unknown / unmapped action — should not normally happen.
    await message.answer("Esa opcion todavia no esta disponible.")


# ---------------------------------------------------------------------------
# Multi-step text handlers
# ---------------------------------------------------------------------------


async def _handle_sandbox_forward(
    message: Message,
    sandbox: SandboxService | None,
    sessions: MenuSessionStore,
) -> None:
    chat_id = _extract_chat_id_from_forward(message)
    if chat_id is None:
        await message.answer(
            "No se pudo extraer el ID del chat del mensaje reenviado. "
            "Asegurate de reenviar un mensaje del chat que quieres activar."
        )
        return

    if sandbox is None:
        await message.answer("El modo de prueba no esta disponible.")
        return

    profiles = sandbox.list_profiles()
    owner_id = message.from_user.id  # type: ignore[union-attr]
    sessions.start(owner_id, "sandbox_profile", sandbox_chat_id=chat_id)
    await message.answer(
        f"Chat detectado: {chat_id}\n\nSelecciona el perfil de prueba:",
        reply_markup=menu_sandbox_profile_picker_keyboard(profiles),
    )


async def _handle_note_text(
    message: Message,
    session: MenuSession,
    profile_admin: ProfileAdminService | None,
) -> None:
    if profile_admin is None or session.vip_user_id is None:
        await message.answer("Gestion de perfiles no disponible.")
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("El texto de la nota no puede estar vacio.")
        return
    result = await profile_admin.add_note(
        message.from_user.id,  # type: ignore[union-attr]
        session.vip_user_id,
        text,
    )
    name = result.display_name or str(session.vip_user_id)
    if result.status == "note_added":
        await message.answer(f"Nota agregada a {name}.")
    else:
        await message.answer(f"No se pudo agregar la nota: {result.status}")


async def _handle_fact_text(
    message: Message,
    session: MenuSession,
    profile_admin: ProfileAdminService | None,
) -> None:
    if profile_admin is None or session.vip_user_id is None:
        await message.answer("Gestion de perfiles no disponible.")
        return
    text = (message.text or "").strip()
    if ":" not in text:
        await message.answer("Formato incorrecto. Usa:\nclave: valor")
        return
    key, _, value = text.partition(":")
    key = key.strip()
    value = value.strip()
    if not key or not value:
        await message.answer("La clave y el valor no pueden estar vacios.")
        return
    result = await profile_admin.set_fact(
        message.from_user.id,  # type: ignore[union-attr]
        session.vip_user_id,
        key,
        value,
    )
    name = result.display_name or str(session.vip_user_id)
    if result.status == "fact_set":
        await message.answer(f"Dato '{key}' agregado a {name}.")
    else:
        await message.answer(f"No se pudo agregar el dato: {result.status}")


async def _handle_rename_text(
    message: Message,
    session: MenuSession,
    vips: VipStore,
) -> None:
    if session.vip_user_id is None:
        return
    new_name = (message.text or "").strip()
    if not new_name:
        await message.answer("El nombre no puede estar vacio.")
        return
    result = await vips.rename(session.vip_user_id, new_name)
    if result is not None:
        await message.answer(f"VIP renombrado a '{new_name}'.")
    else:
        await message.answer(
            f"No se encontro al VIP {session.vip_user_id} o esta inactivo."
        )


__all__ = [
    "HasActiveMenuSession",
    "MenuSession",
    "MenuSessionStore",
    "build_menu_router",
]
