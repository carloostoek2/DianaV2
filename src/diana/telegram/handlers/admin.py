"""Owner private commands: /start, /menu, VIP add/remove, /vip_*, /fp, /resumen."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_service import AdminService, OwnerAuthError
from diana.application.admin_trace_service import AdminTraceService
from diana.application.ports import VipRecord, VipStore
from diana.application.profile_admin_service import ProfileAdminService
from diana.application.sandbox import SandboxService
from diana.application.turn_coordinator import TurnCoordinator
from diana.telegram.handlers.callbacks import (
    ADMIN_MENU_TEXT,
    SESSION_EXPIRED_UX,
    CorrectSessionStore,
)
from diana.telegram.keyboards import (
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
    """English multi-line body for active VIP allowlist."""
    lines = [f"Active VIPs ({len(records)}):"]
    for rec in records:
        name = rec.display_name or "(no name)"
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
    """English profile render for owner DM."""
    name_suffix = f" ({display_name})" if display_name else ""
    header = f"VIP {telegram_user_id}{name_suffix}"
    if empty or not content:
        return f"{header}\nNo profile facts/notes yet."
    facts = content.get("facts") or {}
    notes = content.get("notes") or []
    lines = [header, "Facts:"]
    if isinstance(facts, dict) and facts:
        for k, v in facts.items():
            lines.append(f"  {k}: {v}")
    else:
        lines.append("  (none)")
    lines.append("Notes:")
    if isinstance(notes, list) and notes:
        for i, note in enumerate(notes, start=1):
            if not isinstance(note, dict):
                continue
            date = note.get("date", "")
            text = note.get("text", "")
            lines.append(f"  {i}. [{date}] {text}")
    else:
        lines.append("  (none)")
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
) -> str:
    """Pure admin text dispatcher for unit tests. Returns honest status token."""
    if actor_id is None or actor_id != owner_telegram_id:
        return "ignored_non_owner"

    stripped = (text or "").strip()
    if not stripped:
        return "ignored"

    # Free-text correct follow-up takes priority when session is open.
    # resolve distinguishes expired (UX) vs never-started (silent ignore).
    state, pending_turn = correct_sessions.resolve(actor_id)
    if state == "expired" and not stripped.startswith("/"):
        return "session_expired"
    if state == "live" and pending_turn is not None and not stripped.startswith("/"):
        try:
            result = await admin.handle_correct(
                pending_turn, stripped, actor_id=actor_id
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
) -> Router:
    router = Router(name="admin")
    sessions = correct_sessions or CorrectSessionStore()

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
            admin_metrics=admin_metrics,
            profile_admin=profile_admin,
            sandbox=sandbox,
            coordinator=coordinator,
        )

    _SANDBOX_UX: dict[str, str] = {
        "sandbox_unavailable": "Sandbox disabled",
        "sandbox_usage": (
            "Usage: /sandbox on|off|perfil|perfiles|estado|reset"
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

    @router.message(Command("start", "menu"))
    async def on_menu(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        await message.answer(ADMIN_MENU_TEXT)

    @router.message(Command("add_vip"))
    async def on_add_vip(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "vip_added":
            await message.answer("VIP added")
        else:
            await message.answer("Usage: /add_vip <telegram_user_id> [name]")

    @router.message(Command("remove_vip"))
    async def on_remove_vip(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "vip_removed":
            await message.answer("VIP deactivated")
        elif status == "vip_not_found":
            await message.answer("VIP not found")
        elif status == "forbidden":
            return
        else:
            await message.answer("Usage: /remove_vip <telegram_user_id>")

    @router.message(Command("list_vips"))
    async def on_list_vips(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "vips_empty":
            await message.answer("No active VIPs.")
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
            await message.answer("VIP renamed")
        elif status == "vip_not_found":
            await message.answer("VIP not found")
        else:
            await message.answer(
                "Usage: /rename_vip <telegram_user_id> <name>"
            )

    @router.message(Command("turnos"))
    async def on_turnos(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        if admin_trace is None:
            await message.answer("Trace module not available.")
            return

        filter_chat_id: int | None = None
        parts = (message.text or "").strip().split()
        if len(parts) >= 2:
            try:
                filter_chat_id = int(parts[1])
            except ValueError:
                await message.answer("Usage: /turnos [chat_id]")
                return

        try:
            view = await admin_trace.render_turns_page(0, chat_id=filter_chat_id)
        except Exception:
            logger.exception("Error querying traces")
            await message.answer(
                "System error: unable to query traces. Try again later."
            )
            return
        if view.empty:
            await message.answer("No recent turns found.")
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
            await message.answer("Trace module not available.")
            return

        parts = (message.text or "").split(None, 1)
        if len(parts) < 2:
            await message.answer("Usage: /traza <turn_id>")
            return
        raw_id = parts[1].strip()
        try:
            turn_id = UUID(raw_id)
        except ValueError:
            await message.answer(f"Invalid turn ID: {raw_id}")
            return

        try:
            view = await admin_trace.render_trace_summary(turn_id)
        except Exception:
            logger.exception("Error querying trace")
            await message.answer(
                "System error: unable to query traces. Try again later."
            )
            return
        if view is None:
            await message.answer("Turn not found.")
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
            await message.answer("False positive marked")
        elif status == "fp_unavailable":
            await message.answer("False positive store not available.")
        elif status == "fp_error":
            await message.answer(
                "System error: unable to mark false positive. Try again later."
            )
        elif status == "forbidden":
            return  # fail-closed silent
        else:
            # fp_usage and any unexpected
            await message.answer("Usage: /fp <turn_id>")

    @router.message(Command("vip_profile"))
    async def on_vip_profile(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        if profile_admin is None:
            await message.answer("Profile module not available.")
            return
        status = await _dispatch_token(message)
        if status == "vip_profile_usage":
            await message.answer("Usage: /vip_profile <telegram_user_id>")
            return
        if status == "vip_not_found":
            await message.answer("VIP not found")
            return
        if status == "profile_admin_unavailable":
            await message.answer("Profile module not available.")
            return
        # profile_ok / profile_empty — render body from service
        m = _VIP_PROFILE_RE.match((message.text or "").strip())
        if not m:
            await message.answer("Usage: /vip_profile <telegram_user_id>")
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
            await message.answer(f"Fact set: {key}")
        elif status == "vip_not_found":
            await message.answer("VIP not found")
        elif status == "invalid":
            await message.answer("Usage: /vip_fact <telegram_user_id> <key> <value>")
        elif status == "profile_admin_unavailable":
            await message.answer("Profile module not available.")
        else:
            await message.answer("Usage: /vip_fact <telegram_user_id> <key> <value>")

    @router.message(Command("vip_fact_del"))
    async def on_vip_fact_del(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        m = _VIP_FACT_DEL_RE.match((message.text or "").strip())
        key = m.group(2) if m else ""
        if status == "fact_deleted":
            await message.answer(f"Fact deleted: {key}")
        elif status == "fact_missing":
            await message.answer(f"Fact not found: {key}")
        elif status == "vip_not_found":
            await message.answer("VIP not found")
        elif status == "profile_admin_unavailable":
            await message.answer("Profile module not available.")
        else:
            await message.answer("Usage: /vip_fact_del <telegram_user_id> <key>")

    @router.message(Command("vip_note"))
    async def on_vip_note(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "note_added":
            await message.answer("Note added")
        elif status == "vip_not_found":
            await message.answer("VIP not found")
        elif status == "profile_admin_unavailable":
            await message.answer("Profile module not available.")
        else:
            await message.answer("Usage: /vip_note <telegram_user_id> <text>")

    @router.message(Command("vip_note_del"))
    async def on_vip_note_del(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        status = await _dispatch_token(message)
        if status == "note_deleted":
            await message.answer("Note deleted")
        elif status == "note_missing":
            await message.answer("Note not found")
        elif status == "vip_not_found":
            await message.answer("VIP not found")
        elif status == "profile_admin_unavailable":
            await message.answer("Profile module not available.")
        else:
            await message.answer("Usage: /vip_note_del <telegram_user_id> <index>")

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
                "Error del sistema al cargar métricas. Reintentá más tarde."
            )
            return
        kb = metrics_keyboard() if status == "ok" else None
        await message.answer(body, reply_markup=kb)

    @router.message()
    async def on_owner_text(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        actor_id = message.from_user.id if message.from_user else 0
        # Only handle free-text correct; ignore never-started private chatter.
        state, _ = sessions.resolve(actor_id)
        if state == "none":
            return
        if state == "expired":
            await message.answer(SESSION_EXPIRED_UX)
            return
        status = await handle_admin_text(
            text=message.text or "",
            actor_id=message.from_user.id if message.from_user else None,
            owner_telegram_id=owner_telegram_id,
            vips=vips,
            admin=admin,
            correct_sessions=sessions,
        )
        if status == "corrected":
            await message.answer("Corrected text delivered")
        elif status == "invalid_correct":
            await message.answer("Corrected text must be non-empty")
        elif status == "stale":
            await message.answer(
                "Turn already handled or superseded — nothing delivered"
            )
        elif status == "deliver_failed":
            await message.answer("Delivery failed — try again from the draft buttons")
        elif status == "session_expired":
            await message.answer(SESSION_EXPIRED_UX)

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
