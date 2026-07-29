"""Proactive missed-message recovery on startup — flush pending updates via getUpdates.

Called before ``dispatcher.start_polling()`` so that any updates that arrived
while the bot was offline are fetched, processed through the full middleware
chain, and acknowledged on Telegram's server before the long-polling loop begins.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot, Dispatcher

logger = logging.getLogger("diana.application")


@dataclass
class MissedMessageRecoveryReport:
    """How many pending updates were recovered during startup."""

    recovered_business_messages: int = 0
    recovered_regular_messages: int = 0
    total_updates: int = 0
    total_batches: int = 0


async def recover_missed_updates(
    bot: Bot,
    dispatcher: Dispatcher,
) -> MissedMessageRecoveryReport:
    """Fetch and process all pending updates that arrived during downtime.

    Must be called **before** ``dispatcher.start_polling()`` to avoid competing
    consumers on the ``getUpdates`` queue.

    Calls ``getUpdates`` in a loop (up to 100 updates per batch) with
    ``offset=None``, which starts from the earliest unconfirmed update on
    Telegram's server.  Each ``Update`` is fed through
    ``dispatcher.feed_update()`` so the full middleware chain applies — auth,
    freeze check, forbidden keywords, rate-limit, dedup, business-connection —
    identically to real-time delivery.

    Returns a ``MissedMessageRecoveryReport`` with counts.
    """
    offset: int | None = None  # None = earliest unconfirmed
    recovered_business = 0
    recovered_regular = 0
    total = 0
    batches = 0

    while True:
        updates = await bot.get_updates(
            offset=offset,
            timeout=0,  # return immediately, no long-poll wait
            allowed_updates=["business_message", "message", "callback_query"],
        )
        if not updates:
            break

        batches += 1
        for update in updates:
            if update.business_message:
                recovered_business += 1
            elif update.message:
                recovered_regular += 1

            await dispatcher.feed_update(bot, update)
            offset = update.update_id + 1
            total += 1

    if total:
        logger.info(
            "missed_message_recovery",
            extra={
                "recovered_business_messages": recovered_business,
                "recovered_regular_messages": recovered_regular,
                "total_updates": total,
                "batches": batches,
            },
        )

    return MissedMessageRecoveryReport(
        recovered_business_messages=recovered_business,
        recovered_regular_messages=recovered_regular,
        total_updates=total,
        total_batches=batches,
    )


__all__ = [
    "MissedMessageRecoveryReport",
    "recover_missed_updates",
]
