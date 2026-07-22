"""Owner callback handlers: approve / correct / escalate."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from diana.application.admin_service import AdminService, OwnerAuthError
from diana.telegram.keyboards import parse_callback

logger = logging.getLogger("diana.telegram")

DEFAULT_CORRECT_TTL = timedelta(minutes=15)
ClockFn = Callable[[], datetime]


class CorrectSessionStore:
    """In-process FSM: owner_id → awaiting free-text correct for turn_id.

    Supports TTL (default 15 min) and cancel-by-turn for supersede cleanup.
    """

    def __init__(
        self,
        *,
        ttl: timedelta = DEFAULT_CORRECT_TTL,
        clock: ClockFn | None = None,
    ) -> None:
        self._awaiting: dict[int, tuple[UUID, datetime]] = {}
        self._ttl = ttl
        self._clock: ClockFn = clock or (lambda: datetime.now(UTC))

    def start(self, owner_id: int, turn_id: UUID) -> None:
        self._awaiting[owner_id] = (turn_id, self._clock())

    def pop(self, owner_id: int) -> UUID | None:
        item = self._awaiting.pop(owner_id, None)
        if item is None:
            return None
        turn_id, started = item
        if self._clock() - started > self._ttl:
            return None
        return turn_id

    def get(self, owner_id: int) -> UUID | None:
        item = self._awaiting.get(owner_id)
        if item is None:
            return None
        turn_id, started = item
        if self._clock() - started > self._ttl:
            self._awaiting.pop(owner_id, None)
            return None
        return turn_id

    def cancel(self, owner_id: int) -> None:
        self._awaiting.pop(owner_id, None)

    def cancel_turn(self, turn_id: UUID) -> int:
        """Clear any correct sessions awaiting this turn (supersede / terminal)."""
        removed = 0
        for oid, (tid, _) in list(self._awaiting.items()):
            if tid == turn_id:
                self._awaiting.pop(oid, None)
                removed += 1
        return removed


def _map_delivery_status(result: Any, *, success_token: str) -> str:
    """Map Admin DeliveryResult | None to honest handler tokens."""
    if result is None:
        return "stale"
    success = getattr(result, "success", False)
    if success:
        return success_token
    if getattr(result, "cancelled", False):
        return "stale"
    return "deliver_failed"


async def dispatch_owner_callback(
    *,
    admin: AdminService,
    correct_sessions: CorrectSessionStore,
    callback_data: str,
    actor_id: int | None,
) -> str:
    """Domain dispatch for unit tests. Returns honest status token."""
    parsed = parse_callback(callback_data)
    if parsed is None:
        return "ignored"
    action, turn_id = parsed
    try:
        if action == "approve":
            result = await admin.handle_approve(turn_id, actor_id=actor_id)
            status = _map_delivery_status(result, success_token="approved")
            if status != "approved":
                correct_sessions.cancel_turn(turn_id)
            return status
        if action == "correct":
            if actor_id is None:
                raise OwnerAuthError("missing actor")
            admin._assert_owner(actor_id)  # noqa: SLF001 — intentional thin gate
            if not await admin.is_pending_approval(turn_id):
                correct_sessions.cancel_turn(turn_id)
                return "stale"
            correct_sessions.start(actor_id, turn_id)
            return "awaiting_correct"
        if action == "escalate":
            applied = await admin.handle_owner_escalate(turn_id, actor_id=actor_id)
            correct_sessions.cancel_turn(turn_id)
            return "escalated" if applied else "stale"
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
        if status == "stale":
            await query.answer(
                "Already handled or superseded — no action taken",
                show_alert=True,
            )
            return
        if status == "deliver_failed":
            await query.answer("Delivery failed — try again", show_alert=True)
            return
        await query.answer()

    return router


__all__ = [
    "DEFAULT_CORRECT_TTL",
    "CorrectSessionStore",
    "build_callback_router",
    "dispatch_owner_callback",
]
