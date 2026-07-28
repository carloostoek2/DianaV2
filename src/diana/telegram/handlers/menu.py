"""Hierarchical owner menu — buttons instead of raw slash commands.

Replaces the flat /menu command list with 5 logical categories (VIPs,
Revisar mensajes, Modo de prueba, Métricas, Historial). Each category opens
a submenu of buttons. Actions that need no extra data (list VIPs, view
weekly metrics, etc.) execute immediately. Actions that need data the owner
must type (a telegram id, a name, a chat id) show the exact command to use
instead of guessing it — this keeps the bot friendly for a non-technical
owner without requiring a full text-input wizard for every field.

This router is registered BEFORE build_admin_router in setup.py so that
/start and /menu are handled here instead of the old flat-text menu.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_trace_service import AdminTraceService
from diana.application.ports import VipStore
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
    menu_history_keyboard,
    menu_metrics_keyboard,
    menu_review_keyboard,
    menu_root_keyboard,
    menu_sandbox_keyboard,
    menu_vips_keyboard,
    metrics_keyboard,
    parse_menu_callback,
    staging_candidate_keyboard,
    trace_list_keyboard,
)

logger = logging.getLogger("diana.telegram")

_CATEGORY_KEYBOARDS = {
    "vips": menu_vips_keyboard,
    "review": menu_review_keyboard,
    "sandbox": menu_sandbox_keyboard,
    "metrics": menu_metrics_keyboard,
    "history": menu_history_keyboard,
}

# Actions that just need a copy-pasteable command template (they require
# data only the owner knows: a telegram id, a name, a chat id...).
_USAGE_TEMPLATES: dict[tuple[str, str], str] = {
    ("vips", "add"): (
        "Escribí:\n/add_vip <id_telegram> [nombre]\n\n"
        "Ejemplo:\n/add_vip 123456789 Ana"
    ),
    ("vips", "remove"): "Escribí:\n/remove_vip <id_telegram>",
    ("vips", "rename"): "Escribí:\n/rename_vip <id_telegram> <nombre nuevo>",
    ("vips", "profile"): "Escribí:\n/vip_profile <id_telegram>",
    ("vips", "fact"): "Escribí:\n/vip_fact <id_telegram> <clave> <valor>",
    ("vips", "factdel"): "Escribí:\n/vip_fact_del <id_telegram> <clave>",
    ("vips", "note"): "Escribí:\n/vip_note <id_telegram> <texto>",
    ("vips", "notedel"): "Escribí:\n/vip_note_del <id_telegram> <número de nota>",
    ("review", "fp"): (
        "Escribí:\n/fp <id_del_turno>\n\n"
        "Usalo cuando Diana escaló algo que en realidad no era un problema.\n"
        "El id del turno aparece en Historial → Ver turnos recientes."
    ),
    ("sandbox", "on"): (
        "Escribí:\n/sandbox on <chat_id> [perfil]\n\n"
        "Perfiles disponibles: usá 'Ver perfiles de prueba' para la lista."
    ),
    ("sandbox", "setprofile"): "Escribí:\n/sandbox perfil <nombre_del_perfil>",
    ("history", "trace"): "Escribí:\n/traza <id_del_turno>",
}


def build_menu_router(
    *,
    owner_telegram_id: int,
    vips: VipStore,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    sandbox: SandboxService | None = None,
    staging: StagingService | None = None,
    coordinator: TurnCoordinator | None = None,
) -> Router:
    """Build the router serving /start, /menu, and all m:* menu callbacks."""
    router = Router(name="menu")

    def _is_owner(message: Message) -> bool:
        return is_private_owner_message(message, owner_telegram_id)

    @router.message(Command("start", "menu"))
    async def on_menu(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        await message.answer(MENU_ROOT_TEXT, reply_markup=menu_root_keyboard())

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
        category, action = parsed
        message = callback.message
        await callback.answer()

        if category == "root":
            if isinstance(message, Message):
                await _show(message, MENU_ROOT_TEXT, menu_root_keyboard())
            return

        if action is None:
            build_kb = _CATEGORY_KEYBOARDS.get(category)
            text = MENU_CATEGORY_TEXT.get(category)
            if build_kb is None or text is None or not isinstance(message, Message):
                return
            await _show(message, text, build_kb())
            return

        if not isinstance(message, Message):
            return
        await _dispatch_action(
            message,
            category=category,
            action=action,
            vips=vips,
            admin_trace=admin_trace,
            admin_metrics=admin_metrics,
            sandbox=sandbox,
            staging=staging,
            coordinator=coordinator,
        )

    return router


async def _show(message: Message, text: str, keyboard: Any) -> None:
    """Edit the existing menu message in place; fall back to a new one."""
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except Exception:  # message unchanged / not editable — send fresh
        await message.answer(text, reply_markup=keyboard)


async def _dispatch_action(
    message: Message,
    *,
    category: str,
    action: str,
    vips: VipStore,
    admin_trace: AdminTraceService | None,
    admin_metrics: AdminMetricsService | None,
    sandbox: SandboxService | None,
    staging: StagingService | None,
    coordinator: TurnCoordinator | None,
) -> None:
    # 1) Usage templates — data only the owner knows, no lookup needed.
    template = _USAGE_TEMPLATES.get((category, action))
    if template is not None:
        await message.answer(template)
        return

    # 2) Concrete, zero-argument actions.
    if category == "vips" and action == "list":
        records = await vips.list_active()
        if not records:
            await message.answer("No hay VIPs activos.")
            return
        await message.answer(format_vips_list(records))
        return

    if category == "sandbox":
        if sandbox is None:
            await message.answer("El modo de prueba no está disponible.")
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
                await message.answer("No hay modo de prueba activo en este momento.")
                return
            was = sandbox.deactivate(focus)
            await message.answer(
                f"Modo de prueba desactivado (chat {focus})."
                if was
                else "No había modo de prueba activo."
            )
            return
        if action == "reset":
            focus = sandbox.get_focus_chat_id()
            if focus is None or not sandbox.is_active(focus):
                await message.answer("No hay modo de prueba activo en este momento.")
                return
            if coordinator is None:
                await message.answer("Error del sistema: no se puede reiniciar ahora.")
                return
            await coordinator.reset_chat_session(focus, reason="menu_reset")
            await message.answer(f"Conversación de prueba reiniciada (chat {focus}).")
            return

    if category == "metrics":
        if action == "summary":
            if admin_metrics is None:
                await message.answer("Métricas no disponibles todavía.")
                return
            try:
                body, status = await admin_metrics.render_week_summary()
            except Exception:
                logger.exception("Error loading metrics summary")
                await message.answer("Error del sistema al cargar métricas. Reintentá más tarde.")
                return
            kb = metrics_keyboard() if status == "ok" else None
            await message.answer(body, reply_markup=kb)
            return
        if action == "staging":
            token, rows = await load_pending_staging_list(staging=staging)
            if token == "unavailable":
                await message.answer("El aprendizaje por ejemplos no está disponible.")
                return
            if token == "empty":
                await message.answer("No hay ejemplos pendientes de revisión.")
                return
            for candidate in rows:
                await message.answer(
                    format_staging_candidate_body(candidate),
                    reply_markup=staging_candidate_keyboard(candidate.id),
                )
            return

    if category == "history" and action == "turns":
        if admin_trace is None:
            await message.answer("El historial no está disponible.")
            return
        try:
            view = await admin_trace.render_turns_page(0)
        except Exception:
            logger.exception("Error querying traces")
            await message.answer("Error del sistema al consultar el historial. Reintentá más tarde.")
            return
        if view.empty:
            await message.answer("No hay turnos recientes.")
            return
        kb = trace_list_keyboard(view.turns_data, page=view.page, total_pages=view.total_pages)
        await message.answer(view.text, reply_markup=kb)
        return

    # Unknown / unmapped action — should not normally happen.
    await message.answer("Esa opción todavía no está disponible.")


__all__ = ["build_menu_router"]
