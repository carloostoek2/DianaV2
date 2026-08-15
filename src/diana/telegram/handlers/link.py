"""Link callback router (link:<action>:<event_id>) — before the catch-all."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.types import CallbackQuery

from diana.application.link import LinkCoordinator
from diana.telegram.keyboards import parse_link_callback

logger = logging.getLogger("diana.telegram")


def build_link_callback_router(
    *,
    link: LinkCoordinator,
    owner_telegram_id: int,
) -> Router:
    """Router for the kicked-VIP decision buttons. Include BEFORE the catch-all."""
    router = Router(name="link")

    @router.callback_query(lambda c: c.data and c.data.startswith("link:"))
    async def on_link_action(callback: CallbackQuery, **_: Any) -> None:
        actor_id = callback.from_user.id if callback.from_user else None
        if actor_id != owner_telegram_id:
            await callback.answer("Not authorized", show_alert=True)
            return
        parsed = parse_link_callback(callback.data or "")
        if parsed is None:
            await callback.answer("Invalid callback", show_alert=True)
            return
        action, event_id = parsed
        reply = await link.handle_decision(event_id, action)
        await callback.answer(reply)
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                logger.debug(
                    "link_clear_keyboard_failed",
                    extra={"event_id": event_id, "action": action},
                    exc_info=True,
                )

    return router


__all__ = ["build_link_callback_router"]
