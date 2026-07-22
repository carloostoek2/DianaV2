"""Owner callback handlers: approve / correct / escalate."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from diana.application.admin_service import AdminService, OwnerAuthError
from diana.telegram.keyboards import parse_callback

logger = logging.getLogger("diana.telegram")


class CorrectSessionStore:
    """Minimal in-process FSM: owner_id → awaiting turn_id for free-text correct."""

    def __init__(self) -> None:
        self._awaiting: dict[int, UUID] = {}

    def start(self, owner_id: int, turn_id: UUID) -> None:
        self._awaiting[owner_id] = turn_id

    def pop(self, owner_id: int) -> UUID | None:
        return self._awaiting.pop(owner_id, None)

    def get(self, owner_id: int) -> UUID | None:
        return self._awaiting.get(owner_id)

    def cancel(self, owner_id: int) -> None:
        self._awaiting.pop(owner_id, None)


async def dispatch_owner_callback(
    *,
    admin: AdminService,
    correct_sessions: CorrectSessionStore,
    callback_data: str,
    actor_id: int | None,
) -> str:
    """Domain dispatch for unit tests. Returns status token."""
    parsed = parse_callback(callback_data)
    if parsed is None:
        return "ignored"
    action, turn_id = parsed
    try:
        if action == "approve":
            await admin.handle_approve(turn_id, actor_id=actor_id)
            return "approved"
        if action == "correct":
            if actor_id is None:
                raise OwnerAuthError("missing actor")
            # Auth check first without delivering.
            admin._assert_owner(actor_id)  # noqa: SLF001 — intentional thin gate
            correct_sessions.start(actor_id, turn_id)
            return "awaiting_correct"
        if action == "escalate":
            await admin.handle_owner_escalate(turn_id, actor_id=actor_id)
            return "escalated"
    except OwnerAuthError:
        return "forbidden"
    return "ignored"


def build_callback_router(
    *,
    admin: AdminService,
    correct_sessions: CorrectSessionStore | None = None,
) -> Router:
    router = Router(name="callbacks")
    sessions = correct_sessions or CorrectSessionStore()

    @router.callback_query()
    async def on_callback(query: CallbackQuery, **_: Any) -> None:
        actor_id = query.from_user.id if query.from_user else None
        data = query.data or ""
        status = await dispatch_owner_callback(
            admin=admin,
            correct_sessions=sessions,
            callback_data=data,
            actor_id=actor_id,
        )
        if status == "forbidden":
            await query.answer("Not authorized", show_alert=True)
            return
        if status == "awaiting_correct":
            await query.answer()
            if query.message:
                await query.message.answer(
                    f"Send corrected text for turn {data.split(':', 1)[-1]}"
                )
            return
        if status == "approved":
            await query.answer("Approved")
            return
        if status == "escalated":
            await query.answer("Escalated")
            return
        await query.answer()

    return router


__all__ = [
    "CorrectSessionStore",
    "build_callback_router",
    "dispatch_owner_callback",
]
