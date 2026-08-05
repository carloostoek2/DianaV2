"""Doctrine callback handlers: respond, resolve-with-draft, escalate."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from diana.application.admin_service import AdminService
from diana.application.ports import GrayZoneServicePort
from diana.application.turn_coordinator import (
    ChatLockTimeoutError,
    TurnCoordinator,
)
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
    turn_id: UUID,
) -> str:
    """Handle respond callback: acknowledge and return 'prompted' status."""
    logger.info(
        "doctrine_respond",
        extra={
            "turn_id": str(turn_id),
        },
    )
    return "prompted"


async def handle_doctrine_resolve_with_draft(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
    admin: AdminService | None = None,
) -> str:
    """Resolve using the existing query draft as doctrine, then confirm.

    After ``confirm_and_apply`` closes the query (and unfreezes the VIP),
    ``admin.create_supervised_delivery_from_gray_zone`` creates a supervised
    PendingApproval with the query draft and transitions the turn to
    ``PENDING_APPROVAL``. With ``admin=None`` the behavior is legacy:
    only ``confirm_and_apply`` (no approval creation, no transition). If the
    supervised delivery cannot be created, the turn is escalated as a
    fallback so it never stays stuck in ``gray_zone``.

    Returns status token: 'resolved', 'escalated', 'not_found', or 'error'.
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
        # If confirm_and_apply fails below, resolve_with_doctrine already
        # created an orphan staging candidate. The query stays open so it
        # can be retried or expired later — safe but should be monitored.
        await gray_zone.confirm_and_apply(query.id, candidate.id)
        if admin is not None:
            try:
                created = await admin.create_supervised_delivery_from_gray_zone(
                    turn_id, query
                )
            except ChatLockTimeoutError:
                # Lock contention with the expiry job or an owner callback:
                # the other holder may be creating the approval for this very
                # turn. Escalating would terminalize it mid-flight — report a
                # retryable error. The query is already closed by
                # confirm_and_apply, so reopen it: otherwise the turn would be
                # stranded in gray_zone with a query nothing ever revisits.
                try:
                    await gray_zone.reopen_query(query.id)
                except Exception:
                    logger.exception(
                        "doctrine_resolve_lock_timeout_reopen_error",
                        extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                    )
                logger.warning(
                    "doctrine_resolve_delivery_lock_timeout",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
                return "error"
            except Exception:
                logger.exception(
                    "doctrine_resolve_delivery_error",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
                created = False
            if not created:
                # Supervised delivery unavailable (e.g. legacy query without
                # business_connection_id). The query is already closed, so
                # escalate the turn — never leave it stuck in gray_zone.
                try:
                    await coordinator.transition(turn_id, "escalated")
                except Exception:
                    logger.exception(
                        "doctrine_resolve_fallback_escalate_error",
                        extra={"turn_id": str(turn_id)},
                    )
                    # Double failure: reopen the query so a later run (expiry)
                    # retries instead of stranding the turn in gray_zone.
                    try:
                        await gray_zone.reopen_query(query.id)
                    except Exception:
                        logger.exception(
                            "doctrine_resolve_reopen_error",
                            extra={
                                "turn_id": str(turn_id),
                                "query_id": str(query.id),
                            },
                        )
                    return "error"
                logger.warning(
                    "doctrine_resolve_delivery_fallback_escalated",
                    extra={"turn_id": str(turn_id), "query_id": str(query.id)},
                )
                return "escalated"
        logger.info(
            "doctrine_resolved_with_draft",
            extra={
                "turn_id": str(turn_id),
                "query_id": str(query.id),
                "candidate_id": str(candidate.id),
                "supervised": admin is not None,
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
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    turn_id: UUID,
) -> str:
    """Discard query and escalate the turn.

    Order: coordinator.transition first (fails fast, reversible),
    then discard_and_close (non-reversible side effect).

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
        # Transition first (fails fast, reversible) — then close the query.
        await coordinator.transition(turn_id, "escalated")
        await gray_zone.discard_and_close(query.id)
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


def build_doctrine_router(
    *,
    gray_zone: GrayZoneServicePort,
    coordinator: TurnCoordinator,
    owner_telegram_id: int | None = None,
    admin: AdminService | None = None,
) -> Router:
    """Build a Router with doctrine callback handlers.

    The router is included BEFORE the catch-all callback router so that
    doctrine-specific callbacks (dr:*, dx:*, de:*) are handled first.
    Owner auth mirrors metrics/trace: non-owner answers ``Not authorized``.
    """
    router = Router(name="doctrine")

    def _is_owner(callback: CallbackQuery) -> bool:
        if owner_telegram_id is None:
            return False
        actor = callback.from_user.id if callback.from_user else None
        return actor == owner_telegram_id

    @router.callback_query(lambda c: c.data and c.data.startswith("dr:"))
    async def on_doctrine_respond(callback: CallbackQuery, **_: Any) -> None:
        if not _is_owner(callback):
            await callback.answer("Not authorized", show_alert=True)
            return
        turn_id = parse_doctrine_callback(callback.data or "")
        if turn_id is None:
            await callback.answer("Invalid callback", show_alert=True)
            return

        status = await handle_doctrine_respond(turn_id=turn_id)
        await callback.answer("Opening response prompt...")
        if callback.message:
            await callback.message.answer(
                f"Send your doctrine response text for turn {turn_id}"
            )

    @router.callback_query(lambda c: c.data and c.data.startswith("dx:"))
    async def on_doctrine_resolve_with_draft(
        callback: CallbackQuery, **_: Any
    ) -> None:
        if not _is_owner(callback):
            await callback.answer("Not authorized", show_alert=True)
            return
        turn_id = parse_doctrine_callback(callback.data or "")
        if turn_id is None:
            await callback.answer("Invalid callback", show_alert=True)
            return

        status = await handle_doctrine_resolve_with_draft(
            gray_zone=gray_zone,
            coordinator=coordinator,
            turn_id=turn_id,
            admin=admin,
        )
        text, alert = _RESULT_MESSAGES.get(status, ("Processed", False))
        await callback.answer(text, show_alert=alert)

    @router.callback_query(lambda c: c.data and c.data.startswith("de:"))
    async def on_doctrine_escalate(callback: CallbackQuery, **_: Any) -> None:
        if not _is_owner(callback):
            await callback.answer("Not authorized", show_alert=True)
            return
        turn_id = parse_doctrine_callback(callback.data or "")
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
