"""Proactive missed-message recovery on startup — flush pending updates via getUpdates.

Called before ``dispatcher.start_polling()`` so that any updates that arrived
while the bot was offline are fetched, acknowledged on Telegram's server, and
handed to the middleware chain **without blocking** the rest of boot (health,
jobs, long-polling).

Handlers run as background tasks so VIP human pre-delay (e.g. 120s supervised)
does not stall startup. This matches live polling's ``handle_as_tasks=True``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from aiogram.types import Update

logger = logging.getLogger("diana.application")

# Strong refs so fire-and-forget tasks are not GC'd mid-flight.
_background_tasks: set[asyncio.Task[Any]] = set()


@dataclass
class MissedMessageRecoveryReport:
    """How many pending updates were recovered during startup."""

    recovered_business_messages: int = 0
    recovered_regular_messages: int = 0
    total_updates: int = 0
    total_batches: int = 0
    # Handlers scheduled in background (not necessarily finished).
    handlers_scheduled: int = 0


def _spawn(coro: Any, *, name: str) -> asyncio.Task[Any]:
    task: asyncio.Task[Any] = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def wait_missed_recovery_tasks(*, timeout: float = 30.0) -> None:
    """Await in-flight missed-feed tasks (tests / graceful drain)."""
    pending = [t for t in _background_tasks if not t.done()]
    if not pending:
        return
    await asyncio.wait_for(
        asyncio.gather(*pending, return_exceptions=True),
        timeout=timeout,
    )


async def _feed_one(bot: Bot, dispatcher: Dispatcher, update: Update) -> None:
    try:
        await dispatcher.feed_update(bot, update)
    except BaseException:
        logger.exception(
            "missed_message_recovery_feed_failed",
            extra={"update_id": update.update_id},
        )


async def recover_missed_updates(
    bot: Bot,
    dispatcher: Dispatcher,
) -> MissedMessageRecoveryReport:
    """Fetch and ACK pending updates; process handlers in the background.

    Must be called **before** ``dispatcher.start_polling()`` to avoid competing
    consumers on the ``getUpdates`` queue.

    Drains ``getUpdates`` (timeout=0) and advances the offset so Telegram
    considers the updates acknowledged. Each update is then scheduled via
    ``asyncio.create_task(dispatcher.feed_update(...))`` so pre-delay sleeps
    and the cognitive pipeline do **not** block health/jobs/polling startup.

    Returns a ``MissedMessageRecoveryReport`` with counts (handlers may still
    be running when this returns).
    """
    offset: int | None = None  # None = earliest unconfirmed
    recovered_business = 0
    recovered_regular = 0
    total = 0
    batches = 0
    scheduled = 0

    while True:
        updates = await bot.get_updates(
            offset=offset,
            timeout=0,  # return immediately, no long-poll wait
            allowed_updates=[
                "business_message",
                "edited_business_message",
                "message",
                "callback_query",
            ],
        )
        if not updates:
            break

        batches += 1
        for update in updates:
            if update.business_message:
                recovered_business += 1
            elif update.edited_business_message:
                recovered_business += 1
            elif update.message:
                recovered_regular += 1

            _spawn(
                _feed_one(bot, dispatcher, update),
                name=f"missed_feed_{update.update_id}",
            )
            scheduled += 1
            # Advance offset immediately so the next getUpdates ACKs this id
            # even while the handler is still sleeping pre_delay.
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
                "handlers_scheduled": scheduled,
            },
        )

    return MissedMessageRecoveryReport(
        recovered_business_messages=recovered_business,
        recovered_regular_messages=recovered_regular,
        total_updates=total,
        total_batches=batches,
        handlers_scheduled=scheduled,
    )


__all__ = [
    "MissedMessageRecoveryReport",
    "recover_missed_updates",
    "wait_missed_recovery_tasks",
]
