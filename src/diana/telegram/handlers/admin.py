"""Owner private commands: /start, /menu, VIP add/remove, correct text follow-up."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from diana.application.admin_service import AdminService, OwnerAuthError
from diana.application.admin_trace_service import AdminTraceService
from diana.application.ports import VipStore
from diana.telegram.handlers.callbacks import CorrectSessionStore
from diana.telegram.helpers import _format_relative_time
from diana.telegram.keyboards import trace_detail_keyboard, trace_list_keyboard

logger = logging.getLogger("diana.telegram")

_ADD_RE = re.compile(r"^/add_vip\s+(\d+)(?:\s+(.+))?$", re.IGNORECASE)
_RM_RE = re.compile(r"^/remove_vip\s+(\d+)\s*$", re.IGNORECASE)


async def handle_admin_text(
    *,
    text: str,
    actor_id: int | None,
    owner_telegram_id: int,
    vips: VipStore,
    admin: AdminService,
    correct_sessions: CorrectSessionStore,
    admin_trace: AdminTraceService | None = None,
) -> str:
    """Pure admin text dispatcher for unit tests. Returns honest status token."""
    if actor_id is None or actor_id != owner_telegram_id:
        return "ignored_non_owner"

    stripped = (text or "").strip()
    if not stripped:
        return "ignored"

    # Free-text correct follow-up takes priority when session is open.
    pending_turn = correct_sessions.get(actor_id)
    if pending_turn is not None and not stripped.startswith("/"):
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
        return "vip_removed" if ok else "vip_not_found"

    return "ignored"


def build_admin_router(
    *,
    owner_telegram_id: int,
    vips: VipStore,
    admin: AdminService,
    correct_sessions: CorrectSessionStore | None = None,
    admin_trace: AdminTraceService | None = None,
) -> Router:
    router = Router(name="admin")
    sessions = correct_sessions or CorrectSessionStore()

    def _is_owner(message: Message) -> bool:
        return bool(
            message.from_user and message.from_user.id == owner_telegram_id
        )

    @router.message(Command("start", "menu"))
    async def on_menu(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        await message.answer(
            "Diana F1 admin\n"
            "/add_vip <telegram_user_id> [name]\n"
            "/remove_vip <telegram_user_id>\n"
            "Draft buttons: Approve / Correct / Escalate\n"
            "/turnos — recent turns\n"
            "/traza <id> — trace detail"
        )

    @router.message(Command("add_vip"))
    async def on_add_vip(message: Message, **_: Any) -> None:
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
        if status == "vip_added":
            await message.answer("VIP added")
        else:
            await message.answer("Usage: /add_vip <telegram_user_id> [name]")

    @router.message(Command("remove_vip"))
    async def on_remove_vip(message: Message, **_: Any) -> None:
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
        if status == "vip_removed":
            await message.answer("VIP deactivated")
        elif status == "vip_not_found":
            await message.answer("VIP not found")
        else:
            await message.answer("Usage: /remove_vip <telegram_user_id>")

    @router.message(Command("turnos"))
    async def on_turnos(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        if admin_trace is None:
            await message.answer("Trace module not available.")
            return

        try:
            turns = await admin_trace.get_recent_turns(limit=10, offset=0)
        except Exception:
            logger.exception("Error querying traces")
            await message.answer("System error: unable to query traces. Try again later.")
            return
        if not turns:
            await message.answer("No recent turns found.")
            return

        try:
            total = await admin_trace.count_recent()
        except Exception:
            logger.exception("Error counting traces")
            await message.answer("System error: unable to query traces. Try again later.")
            return
        total_pages = max(1, (total + 9) // 10)
        page = 0
        lines: list[str] = [f"Recent turns (page {page + 1}/{total_pages}):", ""]
        for i, t in enumerate(turns, 1):
            sid = str(t.turn_id)[:8]
            name = t.vip_name or "Unknown"
            ts = _format_relative_time(t.created_at)
            preview = t.message_preview
            lines.append(f"{i}. [{sid}] {name} (chat {t.chat_id}): \"{preview}\" -> {t.decision} ({ts})")

        turns_data = [(t.turn_id, str(t.turn_id)[:8]) for t in turns]
        kb = trace_list_keyboard(turns_data, page=page, total_pages=total_pages)
        await message.answer("\n".join(lines), reply_markup=kb)

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
            trace = await admin_trace.get_full_trace(turn_id)
        except Exception:
            logger.exception("Error querying trace")
            await message.answer("System error: unable to query traces. Try again later.")
            return
        if trace is None:
            await message.answer("Turn not found.")
            return

        sid = str(trace.turn_id)[:8]
        ts = _format_relative_time(trace.created_at)
        vip_name = trace.vip_id and str(trace.vip_id)[:8] or "N/A"
        original = (trace.prompt_text or "")[:200]
        draft = (trace.generated_text or "")[:80]
        decision_action = "N/A"
        if trace.decision:
            decision_action = trace.decision.get("action", "N/A")
        total_ms = 0
        if trace.timings:
            total_ms = int(sum(v for v in trace.timings.values() if isinstance(v, (int, float))))
        status = trace.status or "N/A"

        lines = [
            f"Trace {sid}",
            f"Date: {ts}",
            f"Status: {status}",
            f"Original intent: {original}",
            f"Draft: \"{draft}...\"",
            f"Decision: {decision_action}",
            f"Total time: {total_ms}ms",
        ]
        kb = trace_detail_keyboard(trace.turn_id, timings=trace.timings)
        await message.answer("\n".join(lines), reply_markup=kb)

    @router.message()
    async def on_owner_text(message: Message, **_: Any) -> None:
        if not _is_owner(message):
            return
        # Only handle free-text correct; ignore other private chatter.
        if sessions.get(message.from_user.id if message.from_user else 0) is None:
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

    return router


__all__ = ["build_admin_router", "handle_admin_text"]
