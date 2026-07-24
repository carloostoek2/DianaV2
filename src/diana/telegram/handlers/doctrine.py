"""Doctrine callback handlers: respond, resolve-with-draft, escalate."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from diana.application.ports import GrayZoneQueryView
from diana.application.turn_coordinator import TurnCoordinator
from diana.telegram.keyboards import parse_doctrine_callback

logger = logging.getLogger("diana.telegram")

_RESULT_MESSAGES: dict[str, tuple[str, bool]] = {
    "resolved": ("Resolved and applied", False),
    "escalated": ("Escalated", False),
    "not_found": ("Query not found — already handled", True),
    "error": ("Error processing request", True),
}


async def handle_doctrine_respond(
    *,
    gray_zone: Any,
    turn_id: UUID,
    query: GrayZoneQueryView | None,
) -> str:
    """Handle respond callback: acknowledge and return 'prompted' status."""
    _ = gray_zone
    _ = query
    logger.info(
        "doctrine_respond",
        extra={
            "turn_id": str(turn_id),
            "query_id": str(query.id) if query is not None else None,
        },
    )
    return "prompted"


async def handle_doctrine_resolve_with_draft(
    *,
    gray_zone: Any,
    coordinator: TurnCoordinator,
    turn_id: UUID,
) -> str:
    """Resolve using the existing query draft as doctrine, then confirm.

    Returns status token: 'resolved', 'not_found', or 'error'.
    """
    try:
        query = await gray_zone.get_open_query_by_turn_id(turn_id)
    except Exception:
        logger.exception(
            "doctrine_resolve_lookup_error", extra={"turn_id": str(turn_id)}
        )
        return "error"

    if query is None:
        logger.info("doctrine_resolve_no_query", extra={"turn_id": str(turn_id)})
        return "not_found"

    try:
        candidate = await gray_zone.resolve_with_doctrine(
            query.id,
            query.draft,
            query.draft,
        )
        await gray_zone.confirm_and_apply(query.id, candidate.id)
        logger.info(
            "doctrine_resolved_with_draft",
            extra={
                "turn_id": str(turn_id),
                "query_id": str(query.id),
                "candidate_id": str(candidate.id),
            },
        )
        return "resolved"
    except Exception:
        logger.exception(
            "doctrine_resolve_error",
            extra={"turn_id": str(turn_id), "query_id": str(query.id)},
        )
        return "error"


async def handle_doctrine_escalate(
    *,
    gray_zone: Any,
    coordinator: TurnCoordinator,
    turn_id: UUID,
) -> str:
    """Discard query and escalate the turn.

    Returns status token: 'escalated', 'not_found', or 'error'.
    """
    try:
        query = await gray_zone.get_open_query_by_turn_id(turn_id)
    except Exception:
        logger.exception(
            "doctrine_escalate_lookup_error", extra={"turn_id": str(turn_id)}
        )
        return "error"

    if query is None:
        logger.info("doctrine_escalate_no_query", extra={"turn_id": str(turn_id)})
        return "not_found"

    try:
        await gray_zone.discard_and_close(query.id)
        await coordinator.transition(turn_id, "escalated")
        logger.info(
            "doctrine_escalated",
            extra={
                "turn_id": str(turn_id),
                "query_id": str(query.id),
            },
        )
        return "escalated"
    except Exception:
        logger.exception(
            "doctrine_escalate_error",
            extra={"turn_id": str(turn_id), "query_id": str(query.id)},
        )
        return "error"


def _extract_turn_id(data: str) -> UUID | None:
    """Extract UUID from callback data like dx:<uuid> or de:<uuid>."""
    if not data or ":" not in data:
        return None
    _, raw_id = data.split(":", 1)
    try:
        return UUID(raw_id)
    except ValueError:
        return None


def build_doctrine_router(
    *,
    gray_zone: Any,
    coordinator: TurnCoordinator,
) -> Router:
    """Build a Router with doctrine callback handlers.

    The router is included BEFORE the catch-all callback router so that
    doctrine-specific callbacks (dr:*, dx:*, de:*) are handled first.
    """
    router = Router(name="doctrine")

    @router.callback_query(lambda c: c.data and c.data.startswith("dr:"))
    async def on_doctrine_respond(callback: CallbackQuery, **_: Any) -> None:
        turn_id = parse_doctrine_callback(callback.data or "")
        if turn_id is None:
            await callback.answer("Invalid callback", show_alert=True)
            return

        query = None
        try:
            query = await gray_zone.get_open_query_by_turn_id(turn_id)
        except Exception:
            logger.exception(
                "doctrine_respond_lookup", extra={"turn_id": str(turn_id)}
            )

        status = await handle_doctrine_respond(
            gray_zone=gray_zone,
            turn_id=turn_id,
            query=query,
        )
        if status == "prompted":
            await callback.answer()
            if callback.message:
                await callback.message.answer(
                    f"Send your doctrine response text for turn {turn_id}"
                )
        else:
            await callback.answer("Error — try again", show_alert=True)

    @router.callback_query(lambda c: c.data and c.data.startswith("dx:"))
    async def on_doctrine_resolve_with_draft(
        callback: CallbackQuery, **_: Any
    ) -> None:
        turn_id = _extract_turn_id(callback.data or "")
        if turn_id is None:
            await callback.answer("Invalid callback", show_alert=True)
            return

        status = await handle_doctrine_resolve_with_draft(
            gray_zone=gray_zone,
            coordinator=coordinator,
            turn_id=turn_id,
        )
        text, alert = _RESULT_MESSAGES.get(status, ("Processed", False))
        await callback.answer(text, show_alert=alert)

    @router.callback_query(lambda c: c.data and c.data.startswith("de:"))
    async def on_doctrine_escalate(callback: CallbackQuery, **_: Any) -> None:
        turn_id = _extract_turn_id(callback.data or "")
        if turn_id is None:
            await callback.answer("Invalid callback", show_alert=True)
            return

        status = await handle_doctrine_escalate(
            gray_zone=gray_zone,
            coordinator=coordinator,
            turn_id=turn_id,
        )
        text, alert = _RESULT_MESSAGES.get(status, ("Processed", False))
        await callback.answer(text, show_alert=alert)

    return router


__all__ = [
    "build_doctrine_router",
    "handle_doctrine_respond",
    "handle_doctrine_resolve_with_draft",
    "handle_doctrine_escalate",
]
