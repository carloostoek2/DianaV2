"""Owner private commands: /start, /menu, VIP add/remove, correct text follow-up."""

from __future__ import annotations

import logging
import re
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from diana.application.admin_service import AdminService, OwnerAuthError
from diana.application.ports import VipStore
from diana.telegram.handlers.callbacks import CorrectSessionStore

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
) -> str:
    """Pure admin text dispatcher for unit tests. Returns status token."""
    if actor_id is None or actor_id != owner_telegram_id:
        return "ignored_non_owner"

    stripped = (text or "").strip()
    if not stripped:
        return "ignored"

    # Free-text correct follow-up takes priority when session is open.
    pending_turn = correct_sessions.get(actor_id)
    if pending_turn is not None and not stripped.startswith("/"):
        try:
            await admin.handle_correct(
                pending_turn, stripped, actor_id=actor_id
            )
        except OwnerAuthError:
            return "forbidden"
        except ValueError:
            return "invalid_correct"
        finally:
            correct_sessions.cancel(actor_id)
        return "corrected"

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
            "Draft buttons: Approve / Correct / Escalate"
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

    return router


__all__ = ["build_admin_router", "handle_admin_text"]
