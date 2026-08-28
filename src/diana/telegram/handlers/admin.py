"""Owner private commands: VIP add/remove, /vip_*, /fp, /resumen, /turnos, /traza, /sandbox, /grafo.

The /start and /menu commands live in the menu router (panel), which wins the
match — the legacy admin handler was removed (A12).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_service import AdminService, OwnerAuthError
from diana.application.admin_trace_service import AdminTraceService
from diana.application.ports import GrayZoneServicePort, VipRecord, VipStore
from diana.application.profile_admin_service import ProfileAdminService
from diana.application.sandbox import SandboxService
from diana.application.turn_coordinator import TurnCoordinator
from diana.telegram.handlers.doctrine import (
    DOCTRINE_SCOPE_PROMPT,
    DoctrineSessionStore,
    handle_doctrine_free_text,
)
from diana.telegram.handlers.callbacks import (
    SESSION_EXPIRED_UX,
    CorrectSessionStore,
)
from diana.telegram.keyboards import doctrine_scope_keyboard, reprimand_combo_keyboard

DOCTRINE_SESSION_EXPIRED_UX = (
    "Sesión de doctrina expirada — toca Escribir regla de nuevo"
)

_DOCTRINE_STATUS_UX: dict[str, str] = {
    "doctrine_session_expired": DOCTRINE_SESSION_EXPIRED_UX,
    "doctrine_unavailable": "Módulo de zona gris no disponible",
    "resolved": "Regla guardada — borrador regenerado para tu aprobación",
    "escalated": "Consulta escalada",
    "not_found": "Consulta no encontrada — ya fue resuelta",
    "stale": "Este turno ya fue superado; la consulta quedó cerrada",
    "error": "Error del sistema al guardar la regla",
    "regen_failed": (
        "No se pudo regenerar el borrador; la regla se desactivó. Reintenta."
    ),
    "rejected": "Acción no disponible",
}


async def _answer_doctrine_status(message: Message, status: str) -> None:
    """Map doctrine free-text status tokens to owner-facing UX (fail-open text)."""
    text = _DOCTRINE_STATUS_UX.get(status)
    if text is None:
        # Unknown token (e.g. forbidden) — stay silent, mirroring correct flow.
        return
    try:
        await message.answer(text)
    except Exception:
        logger.exception(
            "doctrine_status_answer_failed",
            extra={"status": status},
        )

from diana.telegram.keyboards import (
    encode_menu,
    menu_back_keyboard,
    metrics_keyboard,
    trace_detail_keyboard,
    trace_list_keyboard,
)

logger = logging.getLogger("diana.telegram")


def is_private_owner_message(message: Message, owner_telegram_id: int) -> bool:
    """True iff sender is the owner and chat is a private DM (fail-closed)."""
    if message.from_user is None or message.from_user.id != owner_telegram_id:
        return False
    chat = message.chat
    return chat is not None and chat.type == "private"


_ADD_RE = re.compile(r"^/add_vip\s+(\d+)(?:\s+(.+))?$", re.IGNORECASE)
_RM_RE = re.compile(r"^/remove_vip\s+(\d+)\s*$", re.IGNORECASE)
_LIST_RE = re.compile(r"^/list_vips(?:@\S+)?\s*$", re.I)
_RENAME_RE = re.compile(r"^/rename_vip(?:@\S+)?\s+(\d+)\s+(.+)$", re.I)
_VIP_PROFILE_RE = re.compile(r"^/vip_profile(?:@\S+)?\s+(\d+)\s*$", re.I)
_VIP_FACT_RE = re.compile(r"^/vip_fact(?:@\S+)?\s+(\d+)\s+(\S+)\s+(.+)$", re.I)
_VIP_FACT_DEL_RE = re.compile(r"^/vip_fact_del(?:@\S+)?\s+(\d+)\s+(\S+)\s*$", re.I)
_VIP_NOTE_RE = re.compile(r"^/vip_note(?:@\S+)?\s+(\d+)\s+(.+)$", re.I)
_VIP_NOTE_DEL_RE = re.compile(r"^/vip_note_del(?:@\S+)?\s+(\d+)\s+(\d+)\s*$", re.I)
_METRICS_CMDS = frozenset({"/resumen", "/metricas"})
_MAX_DISPLAY_NAME_LEN = 64
_PROFILE_CMD_PREFIXES = (
    "/vip_profile",
    "/vip_fact_del",
    "/vip_fact",
    "/vip_note_del",
    "/vip_note",
)


def format_vips_list(records: list[VipRecord]) -> str:
    """Multi-line body for active VIP allowlist."""
    lines = [f"VIPs activos ({len(records)}):"]
    for rec in records:
        name = rec.display_name or "(sin nombre)"
        lines.append(f"  {rec.telegram_user_id} — {name}")
    return "\n".join(lines)


SANDBOX_HELP_TEXT = (
    "Sandbox admin:\n"
    "/sandbox on <chat_id> [profile]\n"
    "/sandbox off [chat_id]\n"
    "/sandbox perfil <name>\n"
    "/sandbox perfiles\n"
    "/sandbox estado\n"
    "/sandbox reset\n"
    "Profiles: nuevo, cercano, distante, intenso, vip_largo, inyeccion_previa\n"
    "Delivery is fake (no real user messages). Learning/staging disabled while ON."
)


def format_sandbox_help() -> str:
    return SANDBOX_HELP_TEXT


def format_sandbox_perfiles(items: list[dict[str, str]]) -> str:
    lines = ["Sandbox profiles:"]
    for item in items:
        name = item.get("name", "?")
        label = item.get("label", name)
        lines.append(f"  {name} — {label}")
    return "\n".join(lines)


async def _dispatch_sandbox(
    *,
    stripped: str,
    sandbox: SandboxService | None,
    coordinator: TurnCoordinator | None,
) -> tuple[str, str | None]:
    """Handle /sandbox… after owner check. Returns (token, optional body)."""
    if sandbox is None:
        return "sandbox_unavailable", None

    # Strip bot suffix on first token only.
    parts = stripped.split()
    if not parts:
        return "sandbox_help", format_sandbox_help()
    # Normalize command token (/sandbox@Bot → /sandbox)
    cmd0 = parts[0].split("@", 1)[0].lower()
    if cmd0 != "/sandbox":
        return "ignored", None
    sub = parts[1].lower() if len(parts) > 1 else ""

    if sub == "" or sub == "help":
        return "sandbox_help", format_sandbox_help()

    if sub == "on":
        if len(parts) < 3:
            return "sandbox_usage", "Usage: /sandbox on <chat_id> [profile]"
        try:
            chat_id = int(parts[2])
        except ValueError:
            return "sandbox_usage", "Usage: /sandbox on <chat_id> [profile]"
        profile = parts[3] if len(parts) > 3 else "nuevo"
        ok, err = sandbox.activate(chat_id, profile)
        if not ok:
            return "sandbox_error", f"Sandbox error: {err}"
        return "sandbox_on", f"Sandbox ON chat {chat_id} — profile: {profile}"

    if sub == "off":
        if len(parts) >= 3:
            try:
                chat_id = int(parts[2])
            except ValueError:
                return "sandbox_usage", "Usage: /sandbox off [chat_id]"
        else:
            chat_id = sandbox.get_focus_chat_id()
            if chat_id is None:
                return "sandbox_not_active", "No sandbox focus"
        was = sandbox.deactivate(chat_id)
        if not was:
            return "sandbox_not_active", f"Sandbox not active for chat {chat_id}"
        return "sandbox_off", f"Sandbox OFF chat {chat_id}"

    if sub == "perfil":
        if len(parts) < 3:
            return "sandbox_usage", "Usage: /sandbox perfil <name>"
        name = parts[2]
        ok, err = sandbox.set_focus_profile(name)
        if not ok:
            if err and "No focused" in err:
                return "sandbox_not_active", "No sandbox focus"
            return "sandbox_error", f"Sandbox error: {err}"
        focus = sandbox.get_focus_chat_id()
        return "sandbox_perfil", f"Sandbox profile {name} on chat {focus}"

    if sub == "perfiles":
        body = format_sandbox_perfiles(sandbox.list_profiles())
        return "sandbox_perfiles", body

    if sub == "estado":
        return "sandbox_estado", sandbox.format_estado()

    if sub == "reset":
        focus = sandbox.get_focus_chat_id()
        if focus is None or not sandbox.is_active(focus):
            return "sandbox_not_active", "No sandbox focus"
        if coordinator is None:
            return "sandbox_error", "Sandbox error: coordinator not wired"
        await coordinator.reset_chat_session(focus, reason="sandbox_reset")
        return (
            "sandbox_reset",
            f"Sandbox session reset for chat {focus} (sandbox still ON)",
        )

    return "sandbox_usage", (
        "Usage: /sandbox on|off|perfil|perfiles|estado|reset"
    )


def format_profile_body(
    *,
    telegram_user_id: int,
    display_name: str | None,
    content: dict | None,
    empty: bool,
) -> str:
    """Profile render for owner DM."""
    name_suffix = f" ({display_name})" if display_name else ""
    header = f"VIP {telegram_user_id}{name_suffix}"
    if empty or not content:
        return f"{header}\nSin datos de perfil todavía."
    facts = content.get("facts") or {}
    notes = content.get("notes") or []
    lines = [header, "Datos:"]
    if isinstance(facts, dict) and facts:
        for k, v in facts.items():
            lines.append(f"  {k}: {v}")
    else:
        lines.append("  (ninguno)")
    lines.append("Notas:")
    if isinstance(notes, list) and notes:
        for i, note in enumerate(notes, start=1):
            if not isinstance(note, dict):
                continue
            date = note.get("date", "")
            text = note.get("text", "")
            lines.append(f"  {i}. [{date}] {text}")
    else:
        lines.append("  (ninguna)")
    return "\n".join(lines)


async def handle_admin_text(
    *,
    text: str,
    actor_id: int | None,
    owner_telegram_id: int,
    vips: VipStore,
    admin: AdminService,
    correct_sessions: CorrectSessionStore,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    profile_admin: ProfileAdminService | None = None,
    sandbox: SandboxService | None = None,
    coordinator: TurnCoordinator | None = None,
    history_seed: object | None = None,
    backfill_queue: object | None = None,
    doctrine_sessions: DoctrineSessionStore | None = None,
    gray_zone: GrayZoneServicePort | None = None,
) -> str:
    """Pure admin text dispatcher for unit tests. Returns honest status token."""
    if actor_id is None or actor_id != owner_telegram_id:
        return "ignored_non_owner"

    stripped = (text or "").strip()
    if not stripped:
        return "ignored"

    # Free-text doctrine response takes priority when session is open
    # (dr: flow — SPEC-FASE2 6.2). resolve distinguishes expired (UX)
    # vs never-started (silent ignore), mirroring correct_sessions.
    if doctrine_sessions is not None and not stripped.startswith("/"):
        state, pending_turn = doctrine_sessions.resolve(actor_id)
        if state == "expired":
            return "doctrine_session_expired"
        if state == "live" and pending_turn is not None:
            if gray_zone is None:
                return "doctrine_unavailable"
            if coordinator is None:
                return "doctrine_unavailable"
            # GAP-11: ask the scope before resolving. Atencion queries have no
            # VIP (vip_id None) — nothing to choose, resolve global directly.
            try:
                query = await gray_zone.get_open_query_by_turn_id(pending_turn)
            except Exception:
                logger.exception(
                    "doctrine_text_lookup_error",
                    extra={"turn_id": str(pending_turn)},
                )
                return "error"
            if query is None:
                doctrine_sessions.cancel(actor_id)
                return "not_found"
            if getattr(query, "vip_id", None) is None:
                doctrine_sessions.cancel(actor_id)
                return await handle_doctrine_free_text(
                    gray_zone=gray_zone,
                    coordinator=coordinator,
                    turn_id=pending_turn,
                    text=stripped,
                    admin=admin,
                    scope="all",
                    actor_id=actor_id,
                )
            doctrine_sessions.attach_text(actor_id, stripped)
            return "doctrine_scope_prompted"

    # Free-text correct follow-up takes priority when session is open.
    # resolve distinguishes expired (UX) vs never-started (silent ignore).
    state, pending_turn = correct_sessions.resolve(actor_id)
    if state == "expired_combo" and not stripped.startswith("/"):
        return "reprimand_lesson_not_saved"
    if state == "expired" and not stripped.startswith("/"):
        return "session_expired"
    if state == "live" and pending_turn is not None and not stripped.startswith("/"):
        sess = correct_sessions.get_session(actor_id)
        if sess is not None and sess.mode == "escalation_reply":
            try:
                result = await admin.handle_escalation_reply(
                    pending_turn, stripped, actor_id=actor_id
                )
            except OwnerAuthError:
                correct_sessions.cancel(actor_id)
                return "forbidden"
            except ValueError:
                # Keep session so owner can re-send non-empty text.
                return "invalid_reply"
            correct_sessions.cancel(actor_id)
            if result is None:
                correct_sessions.cancel_turn(pending_turn)
                return "stale"
            if result.cancelled:
                correct_sessions.cancel_turn(pending_turn)
                return "stale"
            if result.success:
                return "escalation_reply_sent"
            return "deliver_failed"
        if sess is not None and sess.mode == "reprimand" and sess.phase == "reprimand_combo":
            return "reprimand_combo_use_buttons"
        if sess is not None and sess.mode == "reprimand":
            try:
                delivery, candidate_id = await admin.handle_correct_with_candidate(
                    pending_turn,
                    stripped,
                    actor_id=actor_id,
                    # Review round 2: the reprimand flow never shows the sv:
                    # picker, so sess.severity is always None here. Do NOT
                    # fabricate "moderate" — the shadow distribution stays honest
                    # (ledger correction_severity=None; _decrement_for(None) falls
                    # back to the plain decrement either way).
                    severity=None,
                )
            except OwnerAuthError:
                correct_sessions.cancel(actor_id)
                return "forbidden"
            except ValueError:
                return "invalid_correct"
            if delivery is None or getattr(delivery, "cancelled", False):
                correct_sessions.cancel(actor_id)
                correct_sessions.cancel_turn(pending_turn)
                return "stale"
            if not getattr(delivery, "success", False):
                correct_sessions.cancel(actor_id)
                return "deliver_failed"
            if candidate_id is None:
                chat_id = getattr(sess, "chat_id", None)
                in_sandbox = (
                    sandbox is not None
                    and chat_id is not None
                    and sandbox.is_active(chat_id)
                )
                correct_sessions.cancel(actor_id)
                if in_sandbox:
                    # Aislamiento del sandbox: la memoria/lección es efímera
                    # (criterio dueña 2026-08-25); la doctrina sí persiste.
                    # Token distinto para que el mensaje no suene a error.
                    return "reprimand_lesson_not_saved_sandbox"
                return "reprimand_lesson_not_saved"
            correct_sessions.capture_reprimand(
                actor_id,
                candidate_id=candidate_id,
                corrected_text=stripped,
            )
            return "awaiting_reprimand_combo"
        try:
            result = await admin.handle_correct(
                pending_turn,
                stripped,
                actor_id=actor_id,
                severity=sess.severity or "moderate",
            )
        except OwnerAuthError:
            correct_sessions.cancel(actor_id)
            return "forbidden"
        except ValueError:
            # Keep session so owner can re-send non-empty text.
            return "invalid_correct"

        # Clear session after a completed domain attempt (success or no-op).
        correct_sessions.cancel(actor_id)
        if result is None:
            correct_sessions.cancel_turn(pending_turn)
            return "stale"
        if result.success:
            return "corrected"
        if result.cancelled:
            return "stale"
        return "deliver_failed"

    if stripped in {"/start", "/menu"}:
        return "menu"

    # Sandbox admin surface (owner-only; dedicated early block).
    first_token = stripped.split(None, 1)[0].split("@", 1)[0].lower()
    if first_token == "/sandbox":
        token, _body = await _dispatch_sandbox(
            stripped=stripped,
            sandbox=sandbox,
            coordinator=coordinator,
        )
        return token

    # Strip bot suffix if present (/resumen@BotName)
    cmd = stripped.split("@", 1)[0].split(None, 1)[0].lower()
    if cmd in _METRICS_CMDS:
        if admin_metrics is None:
            return "metrics_unavailable"
        summary = await admin_metrics.get_week_summary()
        return "metrics_empty" if summary.status == "empty" else "metrics_ok"

    m_add = _ADD_RE.match(stripped)
    if m_add:
        tg_id = int(m_add.group(1))
        name = (m_add.group(2) or "").strip() or None
        await vips.add(tg_id, display_name=name)
        schedule = getattr(history_seed, "schedule_seed_for_new_vip", None)
        if callable(schedule):
            schedule(tg_id)
        enqueue = getattr(backfill_queue, "schedule_enqueue", None)
        if callable(enqueue):
            enqueue(tg_id)
        return "vip_added"

    m_rm = _RM_RE.match(stripped)
    if m_rm:
        tg_id = int(m_rm.group(1))
        ok = await vips.deactivate(tg_id)
        if not ok:
            return "vip_not_found"
        if profile_admin is not None:
            try:
                await profile_admin.purge_profile_for_telegram_user(actor_id, tg_id)
            except OwnerAuthError:
                # Miswired owner ids: allowlist already revoked; stay silent.
                return "forbidden"
            except Exception:
                # Best-effort purge: deactivate is primary; log residual profile.
                logger.exception(
                    "vip_remove_purge_failed",
                    extra={"tg_id": tg_id},
                )
        return "vip_removed"

    m_list = _LIST_RE.match(stripped)
    if m_list:
        active = await vips.list_active()
        return "vips_empty" if not active else "vips_list"

    m_ren = _RENAME_RE.match(stripped)
    if m_ren:
        tg_id = int(m_ren.group(1))
        name = (m_ren.group(2) or "").strip()
        if not name or len(name) > _MAX_DISPLAY_NAME_LEN:
            return "rename_vip_usage"
        rec = await vips.rename(tg_id, name)
        return "vip_renamed" if rec is not None else "vip_not_found"
    rename_first = stripped.split(None, 1)[0].split("@", 1)[0].lower()
    if rename_first == "/rename_vip":
        return "rename_vip_usage"

    # /vip_* profile commands (owner enrichable facts/notes).
    first_token = stripped.split(None, 1)[0].split("@", 1)[0].lower()
    if first_token in {
        "/vip_profile",
        "/vip_fact",
        "/vip_fact_del",
        "/vip_note",
        "/vip_note_del",
    } or any(first_token.startswith(p) for p in _PROFILE_CMD_PREFIXES):
        if profile_admin is None:
            return "profile_admin_unavailable"

        m_prof = _VIP_PROFILE_RE.match(stripped)
        if m_prof:
            tg_id = int(m_prof.group(1))
            result = await profile_admin.show_profile(actor_id, tg_id)
            return result.status
        if first_token == "/vip_profile":
            return "vip_profile_usage"

        m_fact = _VIP_FACT_RE.match(stripped)
        if m_fact:
            tg_id = int(m_fact.group(1))
            key = m_fact.group(2)
            value = m_fact.group(3)
            result = await profile_admin.set_fact(actor_id, tg_id, key, value)
            return result.status
        if first_token == "/vip_fact":
            return "vip_fact_usage"

        m_fact_del = _VIP_FACT_DEL_RE.match(stripped)
        if m_fact_del:
            tg_id = int(m_fact_del.group(1))
            key = m_fact_del.group(2)
            result = await profile_admin.delete_fact(actor_id, tg_id, key)
            return result.status
        if first_token == "/vip_fact_del":
            return "vip_fact_del_usage"

        m_note = _VIP_NOTE_RE.match(stripped)
        if m_note:
            tg_id = int(m_note.group(1))
            note_text = m_note.group(2)
            result = await profile_admin.add_note(actor_id, tg_id, note_text)
            return result.status
        if first_token == "/vip_note":
            return "vip_note_usage"

        m_note_del = _VIP_NOTE_DEL_RE.match(stripped)
        if m_note_del:
            tg_id = int(m_note_del.group(1))
            index_1 = int(m_note_del.group(2))
            result = await profile_admin.delete_note(actor_id, tg_id, index_1)
            return result.status
        if first_token == "/vip_note_del":
            return "vip_note_del_usage"

        return "ignored"

    # /fp <turn_id> — mark escalation false positive (owner mark store).
    # First token may include bot suffix (/fp@BotName).
    parts = stripped.split(None, 1)
    first = parts[0].split("@", 1)[0].lower()
    if first == "/fp":
        if len(parts) < 2 or not parts[1].strip():
            return "fp_usage"
        raw_id = parts[1].strip().split(None, 1)[0]
        try:
            turn_id = UUID(raw_id)
        except ValueError:
            return "fp_usage"
        try:
            ok = await admin.mark_false_positive(turn_id, actor_id=actor_id)
        except OwnerAuthError:
            return "forbidden"
        except Exception:
            # Store/DB faults — surface token for owner system-error UX (mirror /traza).
            logger.exception(
                "fp_mark_failed",
                extra={"turn_id": str(turn_id)},
            )
            return "fp_error"
        return "fp_marked" if ok else "fp_unavailable"

    return "ignored"


def build_admin_router(
    *,
    owner_telegram_id: int,
    vips: VipStore,
    admin: AdminService,
    correct_sessions: CorrectSessionStore | None = None,
    admin_trace: AdminTraceService | None = None,
    admin_metrics: AdminMetricsService | None = None,
    profile_admin: ProfileAdminService | None = None,
    sandbox: SandboxService | None = None,
    coordinator: TurnCoordinator | None = None,
    history_seed: object | None = None,
    backfill_queue: object | None = None,
    doctrine_sessions: DoctrineSessionStore | None = None,
    gray_zone: GrayZoneServicePort | None = None,
) -> Router:
    router = Router(name="admin")
    sessions = correct_sessions or CorrectSessionStore()
    doctrine_s = doctrine_sessions or DoctrineSessionStore()

    def _is_owner(message: Message) -> bool:
        # Owner identity + private DM only (SEC-VIP-01: no group leak).
        return is_private_owner_message(message, owner_telegram_id)

    async def _dispatch_token(message: Message) -> str:
        return await handle_admin_text(
            text=message.text or "",
            actor_id=message.from_user.id if message.from_user else None,
            owner_telegram_id=owner_telegram_id,
            vips=vips,
            admin=admin,
            correct_sessions=sessions,
            admin_trace=admin_trace,
            history_seed=history_seed,
            admin_metrics=admin_metrics,
            profile_admin=profile_admin,
            sandbox=sandbox,
            coordinator=coordinator,
            backfill_queue=backfill_queue,
            doctrine_sessions=doctrine_s,
            gray_zone=gray_zone,
        )

    _SANDBOX_UX: dict[str, str] = {
        "sandbox_unavailable": "Sandbox deshabilitado",
        "sandbox_usage": (
            "Uso: /sandbox on|off|perfil|perfiles|estado|reset"
        ),
    }

    @router.message(Command("sandbox"))
    async def on_sandbox(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        token, body = await _dispatch_sandbox(
            stripped=(message.text or "").strip(),
            sandbox=sandbox,
            coordinator=coordinator,
        )
        if body is not None:
            await message.answer(body)
            return
        if token in _SANDBOX_UX:
            await message.answer(_SANDBOX_UX[token])
            return
        # Fallback tokens without body (should be rare).
        if token == "sandbox_help":
            await message.answer(format_sandbox_help())
            return
        await message.answer(f"Sandbox: {token}")

    # Telegram Mini App: grafo del sistema (servido vía Cloudflare Tunnel).
    # GRAFO_URL/GRAFO_TOKEN env-overridable: el token es el mismo
    # UNDERSTAND_ACCESS_TOKEN del servidor del dashboard (grafo.srtakinky.pics).
    _grafo_base = os.getenv("GRAFO_URL", "https://grafo.srtakinky.pics").rstrip("/")
    _grafo_token = os.getenv("GRAFO_TOKEN", "")
    GRAFO_URL = f"{_grafo_base}/?token={_grafo_token}" if _grafo_token else _grafo_base

    @router.message(Command("grafo"))
    async def on_grafo(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🧠 Abrir grafo de conocimiento",
                        web_app=WebAppInfo(url=GRAFO_URL),
                    )
                ]
            ]
        )
        await message.answer(
            "El grafo interactivo del sistema (código + arquitectura):",
            reply_markup=kb,
        )

    @router.message(Command("add_vip"))
    async def on_add_vip(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "vip_added":
            await message.answer("VIP agregado")
        else:
            await message.answer("Uso: /add_vip <id_usuario> [nombre]")

    @router.message(Command("remove_vip"))
    async def on_remove_vip(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "vip_removed":
            await message.answer("VIP desactivado")
        elif status == "vip_not_found":
            await message.answer("VIP no encontrado")
        elif status == "forbidden":
            return
        else:
            await message.answer("Uso: /remove_vip <id_usuario>")

    @router.message(Command("list_vips"))
    async def on_list_vips(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "vips_empty":
            await message.answer("No hay VIPs activos.")
            return
        if status == "vips_list":
            records = await vips.list_active()
            await message.answer(format_vips_list(records))
            return

    @router.message(Command("rename_vip"))
    async def on_rename_vip(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "vip_renamed":
            await message.answer("VIP renombrado")
        elif status == "vip_not_found":
            await message.answer("VIP no encontrado")
        else:
            await message.answer(
                "Uso: /rename_vip <id_usuario> <nombre>"
            )

    @router.message(Command("turnos"))
    async def on_turnos(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        if admin_trace is None:
            await message.answer("Módulo de trazas no disponible.")
            return

        filter_chat_id: int | None = None
        parts = (message.text or "").strip().split()
        if len(parts) >= 2:
            try:
                filter_chat_id = int(parts[1])
            except ValueError:
                await message.answer("Uso: /turnos [id_chat]")
                return

        try:
            view = await admin_trace.render_turns_page(0, chat_id=filter_chat_id)
        except Exception:
            logger.exception("Error querying traces")
            await message.answer(
                "Error del sistema al consultar las trazas. Inténtalo más tarde."
            )
            return
        if view.empty:
            await message.answer("No se encontraron turnos recientes.")
            return
        kb = trace_list_keyboard(
            view.turns_data, page=view.page, total_pages=view.total_pages
        )
        await message.answer(view.text, reply_markup=kb)

    @router.message(Command("traza"))
    async def on_traza(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        if admin_trace is None:
            await message.answer("Módulo de trazas no disponible.")
            return

        parts = (message.text or "").split(None, 1)
        if len(parts) < 2:
            await message.answer("Uso: /traza <id_turno>")
            return
        raw_id = parts[1].strip()
        try:
            turn_id = UUID(raw_id)
        except ValueError:
            await message.answer(f"ID de turno inválido: {raw_id}")
            return

        try:
            view = await admin_trace.render_trace_summary(turn_id)
        except Exception:
            logger.exception("Error querying trace")
            await message.answer(
                "Error del sistema al consultar la traza. Inténtalo más tarde."
            )
            return
        if view is None:
            await message.answer("Turno no encontrado.")
            return
        kb = trace_detail_keyboard(view.turn_id, timings=view.timings)
        await message.answer(view.text, reply_markup=kb)

    @router.message(Command("fp"))
    async def on_fp(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await handle_admin_text(
            text=message.text or "",
            actor_id=message.from_user.id if message.from_user else None,
            owner_telegram_id=owner_telegram_id,
            vips=vips,
            admin=admin,
            correct_sessions=sessions,
        )
        if status == "fp_marked":
            await message.answer("Falsa alarma marcada")
        elif status == "fp_unavailable":
            await message.answer("Almacén de falsas alarmas no disponible.")
        elif status == "fp_error":
            await message.answer(
                "Error del sistema al marcar falsa alarma. Inténtalo más tarde."
            )
        elif status == "forbidden":
            return  # fail-closed silent
        else:
            # fp_usage and any unexpected
            await message.answer("Uso: /fp <id_turno>")

    @router.message(Command("vip_profile"))
    async def on_vip_profile(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        if profile_admin is None:
            await message.answer("Módulo de perfil no disponible.")
            return
        status = await _dispatch_token(message)
        if status == "vip_profile_usage":
            await message.answer("Uso: /vip_profile <id_usuario>")
            return
        if status == "vip_not_found":
            await message.answer("VIP no encontrado")
            return
        if status == "profile_admin_unavailable":
            await message.answer("Módulo de perfil no disponible.")
            return
        # profile_ok / profile_empty — render body from service
        m = _VIP_PROFILE_RE.match((message.text or "").strip())
        if not m:
            await message.answer("Uso: /vip_profile <id_usuario>")
            return
        tg_id = int(m.group(1))
        try:
            result = await profile_admin.show_profile(
                message.from_user.id if message.from_user else None, tg_id
            )
        except OwnerAuthError:
            return
        body = format_profile_body(
            telegram_user_id=tg_id,
            display_name=result.display_name,
            content=result.content if isinstance(result.content, dict) else None,
            empty=result.status == "profile_empty",
        )
        await message.answer(body)

    @router.message(Command("vip_fact"))
    async def on_vip_fact(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "fact_set":
            m = _VIP_FACT_RE.match((message.text or "").strip())
            key = m.group(2) if m else ""
            await message.answer(f"Dato guardado: {key}")
        elif status == "vip_not_found":
            await message.answer("VIP no encontrado")
        elif status == "invalid":
            await message.answer("Uso: /vip_fact <id_usuario> <clave> <valor>")
        elif status == "profile_admin_unavailable":
            await message.answer("Módulo de perfil no disponible.")
        else:
            await message.answer("Uso: /vip_fact <id_usuario> <clave> <valor>")

    @router.message(Command("vip_fact_del"))
    async def on_vip_fact_del(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        m = _VIP_FACT_DEL_RE.match((message.text or "").strip())
        key = m.group(2) if m else ""
        if status == "fact_deleted":
            await message.answer(f"Dato eliminado: {key}")
        elif status == "fact_missing":
            await message.answer(f"Dato no encontrado: {key}")
        elif status == "vip_not_found":
            await message.answer("VIP no encontrado")
        elif status == "profile_admin_unavailable":
            await message.answer("Módulo de perfil no disponible.")
        else:
            await message.answer("Uso: /vip_fact_del <id_usuario> <clave>")

    @router.message(Command("vip_note"))
    async def on_vip_note(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "note_added":
            await message.answer("Nota agregada")
        elif status == "vip_not_found":
            await message.answer("VIP no encontrado")
        elif status == "profile_admin_unavailable":
            await message.answer("Módulo de perfil no disponible.")
        else:
            await message.answer("Uso: /vip_note <id_usuario> <texto>")

    @router.message(Command("vip_note_del"))
    async def on_vip_note_del(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "note_deleted":
            await message.answer("Nota eliminada")
        elif status == "note_missing":
            await message.answer("Nota no encontrada")
        elif status == "vip_not_found":
            await message.answer("VIP no encontrado")
        elif status == "profile_admin_unavailable":
            await message.answer("Módulo de perfil no disponible.")
        else:
            await message.answer("Uso: /vip_note_del <id_usuario> <índice>")

    @router.message(Command("resumen", "metricas"))
    async def on_resumen(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        if admin_metrics is None:
            await message.answer("Métricas no disponibles todavía.")
            return
        try:
            body, status = await admin_metrics.render_week_summary()
        except Exception:
            logger.exception("Error loading metrics summary")
            await message.answer(
                "Error del sistema al cargar métricas. Inténtalo más tarde."
            )
            return
        # A10: even the empty/legacy case keeps a way back to the owner panel.
        kb = metrics_keyboard() if status == "ok" else menu_back_keyboard(encode_menu("root"))
        await message.answer(body, reply_markup=kb)

    @router.message()
    async def on_owner_text(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        actor_id = message.from_user.id if message.from_user else 0

        # Pending doctrine session handling (dr: free-text response).
        if doctrine_s is not None:
            d_state, _ = doctrine_s.resolve(actor_id)
            if d_state == "expired":
                await message.answer(DOCTRINE_SESSION_EXPIRED_UX)
                return
            if d_state == "live":
                status = await handle_admin_text(
                    text=message.text or "",
                    actor_id=message.from_user.id if message.from_user else None,
                    owner_telegram_id=owner_telegram_id,
                    vips=vips,
                    admin=admin,
                    correct_sessions=sessions,
                    doctrine_sessions=doctrine_s,
                    gray_zone=gray_zone,
                    coordinator=coordinator,
                    sandbox=sandbox,
                )
                if status == "doctrine_scope_prompted":
                    # GAP-11: the doctrine text is stored; ask the scope now.
                    pending_turn = doctrine_s.peek_turn_id(actor_id)
                    if pending_turn is not None:
                        try:
                            await message.answer(
                                DOCTRINE_SCOPE_PROMPT,
                                reply_markup=doctrine_scope_keyboard(pending_turn),
                            )
                        except Exception:
                            logger.exception(
                                "doctrine_scope_prompt_failed",
                                extra={"turn_id": str(pending_turn)},
                            )
                    return
                await _answer_doctrine_status(message, status)
                return

        # Existing correct session handling.
        state, _ = sessions.resolve(actor_id)
        if state == "none":
            return
        if state == "expired":
            await message.answer(SESSION_EXPIRED_UX)
            return
        if state == "expired_combo":
            await message.answer(
                "No se guardó la lección. El texto ya se envió al VIP."
            )
            return
        status = await handle_admin_text(
            text=message.text or "",
            actor_id=message.from_user.id if message.from_user else None,
            owner_telegram_id=owner_telegram_id,
            vips=vips,
            admin=admin,
            correct_sessions=sessions,
            sandbox=sandbox,
        )
        if status == "corrected":
            await message.answer("Texto corregido enviado")
        elif status == "invalid_correct":
            await message.answer("El texto corregido no puede estar vacío")
        elif status == "stale":
            await message.answer(
                "El turno ya fue resuelto o reemplazado — no se envió nada"
            )
        elif status == "deliver_failed":
            await message.answer("Error al enviar — inténtalo de nuevo desde los botones del borrador")
        elif status == "session_expired":
            await message.answer(SESSION_EXPIRED_UX)
        elif status == "awaiting_reprimand_combo":
            turn_id = sessions.get(actor_id)
            markup = reprimand_combo_keyboard(turn_id) if turn_id is not None else None
            await message.answer(
                "Texto enviado al VIP. Elige cómo guardar la lección:",
                reply_markup=markup,
            )
        elif status == "reprimand_combo_use_buttons":
            await message.answer(
                "Usa los botones para guardar la lección. El texto ya se envió."
            )
        elif status == "reprimand_lesson_not_saved":
            await message.answer(
                "No se guardó la lección. El texto ya se envió al VIP."
            )
        elif status == "reprimand_lesson_not_saved_sandbox":
            await message.answer(
                "Estás en sandbox: la lección no se guarda (aislamiento), "
                "pero el texto ya se envió al VIP."
            )

    return router


__all__ = [
    "build_admin_router",
    "format_profile_body",
    "format_sandbox_help",
    "format_sandbox_perfiles",
    "format_vips_list",
    "handle_admin_text",
    "is_private_owner_message",
    "SANDBOX_HELP_TEXT",
]
