"""Staging promote/discard callbacks + owner /staging list (sp:/sd:).

Dedicated router included BEFORE the catch-all callback router so prefixes
``sp:`` / ``sd:`` are not swallowed. Writes go through StagingService only.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from diana.application.staging_service import (
    AtencionPromoteBlocked,
    StagingService,
)
from diana.telegram.keyboards import (
    parse_staging_callback,
    staging_candidate_keyboard,
    staging_discard_confirm_keyboard,
)

logger = logging.getLogger("diana.telegram")

_SNIPPET_MAX = 80

STAGING_UNAVAILABLE_UX = "Staging not available"
STAGING_EMPTY_UX = "No pending example candidates"

_TOKEN_UX: dict[str, tuple[str, bool]] = {
    "promoted": ("Promoted", False),
    "discarded": ("Discarded", False),
    "forbidden": ("Not authorized", True),
    "unavailable": (STAGING_UNAVAILABLE_UX, True),
    "invalid": ("Invalid callback", True),
    "stale": ("Already handled or not found", True),
    "atencion_blocked": ("Atencion corrections cannot become VIP examples", True),
}


def _truncate(text: str, max_len: int = _SNIPPET_MAX) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def format_staging_candidate_body(candidate: Any) -> str:
    """Owner-facing body for one pending example candidate."""
    cid = str(getattr(candidate, "id", ""))
    short = cid[:8] if cid else "?"
    payload = getattr(candidate, "payload", None) or {}
    original = _truncate(str(payload.get("original_draft", "")))
    corrected = _truncate(str(payload.get("corrected_text", "")))
    return (
        f"Candidate {short}\n"
        f"Original: {original}\n"
        f"Corrected: {corrected}"
    )


async def load_pending_staging_list(
    *,
    staging: StagingService | None,
    limit: int = 10,
) -> tuple[str, list[Any]]:
    """Load pending example queue. Returns (token, rows).

    Tokens: unavailable | empty | listed
    """
    if staging is None:
        return "unavailable", []
    rows = await staging.list_pending_examples(limit=limit)
    if not rows:
        return "empty", []
    return "listed", list(rows)


async def dispatch_staging_callback(
    *,
    staging: StagingService | None,
    callback_data: str,
    actor_id: int | None,
    owner_telegram_id: int,
) -> str:
    """Pure staging callback dispatch. Returns status token (no Telegram I/O)."""
    if actor_id is None or actor_id != owner_telegram_id:
        return "forbidden"
    if staging is None:
        return "unavailable"
    parsed = parse_staging_callback(callback_data or "")
    if parsed is None:
        return "invalid"
    action, candidate_id = parsed
    try:
        if action == "promote":
            await staging.promote_to_example(candidate_id)
            logger.info(
                "staging_promoted",
                extra={
                    "candidate_id": str(candidate_id),
                    "actor_id": actor_id,
                },
            )
            return "promoted"
        if action == "discard":
            # A4: the first tap only arms the two-step confirm — nothing is
            # deleted until the owner confirms with sd:<id>:confirm.
            return "discard_confirm_prompt"
        if action == "discard_confirm":
            await staging.discard(candidate_id)
            logger.info(
                "staging_discarded",
                extra={
                    "candidate_id": str(candidate_id),
                    "actor_id": actor_id,
                },
            )
            return "discarded"
        if action == "discard_cancel":
            return "discard_cancelled"
    except AtencionPromoteBlocked:
        logger.info(
            "staging_atencion_promote_blocked",
            extra={
                "candidate_id": str(candidate_id),
                "actor_id": actor_id,
                "action": action,
            },
        )
        return "atencion_blocked"
    except ValueError:
        logger.info(
            "staging_stale",
            extra={
                "candidate_id": str(candidate_id),
                "actor_id": actor_id,
                "action": action,
            },
        )
        return "stale"
    return "invalid"


def build_staging_router(
    *,
    staging: StagingService | None,
    owner_telegram_id: int,
) -> Router:
    """Build router for /staging + sp:/sd: callbacks. Include before catch-all."""
    router = Router(name="staging")

    def _is_private_owner(message: Message) -> bool:
        if message.from_user is None or message.from_user.id != owner_telegram_id:
            return False
        chat = message.chat
        return chat is not None and chat.type == "private"

    @router.message(Command("staging"))
    async def on_staging_list(message: Message, **_: Any) -> None:
        if not _is_private_owner(message):
            return
        token, rows = await load_pending_staging_list(staging=staging)
        if token == "unavailable":
            await message.answer(STAGING_UNAVAILABLE_UX)
            return
        if token == "empty":
            await message.answer(STAGING_EMPTY_UX)
            return
        await message.answer(f"Pending examples ({len(rows)}):")
        for row in rows:
            await message.answer(
                format_staging_candidate_body(row),
                reply_markup=staging_candidate_keyboard(row.id),
            )

    @router.callback_query(
        lambda c: c.data is not None
        and (c.data.startswith("sp:") or c.data.startswith("sd:"))
    )
    async def on_staging_action(callback: CallbackQuery, **_: Any) -> None:
        actor_id = callback.from_user.id if callback.from_user else None
        token = await dispatch_staging_callback(
            staging=staging,
            callback_data=callback.data or "",
            actor_id=actor_id,
            owner_telegram_id=owner_telegram_id,
        )
        parsed = parse_staging_callback(callback.data or "")
        candidate_id = parsed[1] if parsed is not None else None

        if token == "discard_confirm_prompt":
            # A4: first discard tap swaps in the confirm keyboard; the body
            # text stays put, so "No, mantener" can simply swap it back.
            await callback.answer()
            if candidate_id is not None and callback.message is not None:
                try:
                    await callback.message.edit_reply_markup(
                        reply_markup=staging_discard_confirm_keyboard(candidate_id)
                    )
                except Exception:
                    logger.debug(
                        "staging_show_confirm_failed",
                        extra={"actor_id": actor_id},
                        exc_info=True,
                    )
            return
        if token == "discard_cancelled":
            await callback.answer()
            if candidate_id is not None and callback.message is not None:
                try:
                    await callback.message.edit_reply_markup(
                        reply_markup=staging_candidate_keyboard(candidate_id)
                    )
                except Exception:
                    logger.debug(
                        "staging_restore_keyboard_failed",
                        extra={"actor_id": actor_id},
                        exc_info=True,
                    )
            return

        text, alert = _TOKEN_UX.get(token, ("Processed", False))
        await callback.answer(text, show_alert=alert)
        if token in {"promoted", "discarded"} and callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                logger.debug(
                    "staging_clear_keyboard_failed",
                    extra={"actor_id": actor_id},
                    exc_info=True,
                )

    return router


__all__ = [
    "STAGING_EMPTY_UX",
    "STAGING_UNAVAILABLE_UX",
    "build_staging_router",
    "dispatch_staging_callback",
    "format_staging_candidate_body",
    "load_pending_staging_list",
]
