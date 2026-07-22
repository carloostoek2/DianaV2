"""BehaviorEngine — sequences human-like delivery; never decides or calls LLM."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

from diana.application.ports import DeliveryRecord, PendingDeliveryStore
from diana.behavior.ports import (
    Clock,
    DelayPolicy,
    DeliveryContext,
    DeliveryResult,
    TelegramActuatorPort,
)
from diana.behavior.timer_manager import TimerManager

logger = logging.getLogger("diana.behavior")


class BehaviorEngine:
    """Act messages via ports: delay → read → typing → send; cancel-aware."""

    def __init__(
        self,
        actuator: TelegramActuatorPort,
        deliveries: PendingDeliveryStore,
        *,
        clock: Clock,
        delay_policy: DelayPolicy,
        timers: TimerManager | None = None,
    ) -> None:
        self._actuator = actuator
        self._deliveries = deliveries
        self._clock = clock
        self._delay = delay_policy
        self._timers = timers or TimerManager()

    async def deliver(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
        decision: Any | None = None,
    ) -> DeliveryResult:
        """Run the delivery sequence for ``texts`` toward ``ctx.chat_id``.

        ``turn_id`` is required for pending_deliveries FK and cancel scope.
        ``decision`` is stored as a dump for reconstructability only.
        """
        bc = (ctx.business_connection_id or "").strip()
        if not bc:
            return DeliveryResult(
                success=False,
                error="business_connection_id is required",
            )

        delivery_id = uuid4()
        decision_dump: dict = {}
        if decision is not None:
            if hasattr(decision, "model_dump"):
                decision_dump = decision.model_dump(mode="json")
            elif isinstance(decision, dict):
                decision_dump = dict(decision)

        record = DeliveryRecord(
            id=delivery_id,
            chat_id=ctx.chat_id,
            business_connection_id=bc,
            texts=list(texts),
            decision=decision_dump,
            scheduled_at=self._clock.now(),
            status="pending",
            turn_id=turn_id,
            vip_id=ctx.vip_id,
        )
        await self._deliveries.insert_pending(record)

        # Track the currently executing task (caller may wrap; we use current).
        current = asyncio.current_task()
        if current is not None:
            await self._timers.register(ctx.chat_id, turn_id, current)

        try:
            await self._deliveries.update_status(delivery_id, "delivering")
            initial = self._delay.initial_delay_seconds()
            await self._clock.sleep(initial)

            if ctx.telegram_message_id is not None:
                await self._actuator.read_business_message(
                    ctx.chat_id,
                    ctx.telegram_message_id,
                    business_connection_id=bc,
                )

            typing_for = texts[0] if texts else ""
            typing_secs = self._delay.typing_duration_seconds(typing_for)
            await self._actuator.send_chat_action(
                ctx.chat_id,
                "typing",
                business_connection_id=bc,
            )
            await self._clock.sleep(typing_secs)

            message_ids: list[int] = []
            for text in texts:
                mid = await self._actuator.send_message(
                    ctx.chat_id,
                    text,
                    business_connection_id=bc,
                )
                message_ids.append(mid)

            await self._deliveries.update_status(delivery_id, "done")
            logger.info(
                "delivery_done",
                extra={"turn_id": str(turn_id), "chat_id": ctx.chat_id},
            )
            return DeliveryResult(
                success=True,
                message_ids=message_ids,
                actual_delay_seconds=initial,
                typing_duration_seconds=typing_secs,
            )
        except asyncio.CancelledError:
            await self._safe_mark_cancelled(delivery_id)
            logger.info(
                "delivery_cancelled",
                extra={"turn_id": str(turn_id), "chat_id": ctx.chat_id},
            )
            return DeliveryResult(success=False, cancelled=True, error="cancelled")
        except Exception as exc:  # noqa: BLE001 — surface as delivery failure
            await self._safe_mark_cancelled(delivery_id, status="cancelled")
            return DeliveryResult(success=False, error=str(exc))

    async def cancel_pending(
        self, chat_id: int, reason: str = "new_message"
    ) -> None:
        """Cancel in-flight tasks for chat_id + mark pending/delivering cancelled.

        Idempotent: safe to call when nothing is pending.
        """
        _ = reason
        await self._timers.cancel_chat(chat_id)
        n = await self._deliveries.cancel_for_chat(chat_id)
        logger.info(
            "cancel_pending",
            extra={"chat_id": chat_id, "rows_cancelled": n, "reason": reason},
        )

    async def _safe_mark_cancelled(
        self, delivery_id: UUID, *, status: str = "cancelled"
    ) -> None:
        try:
            await self._deliveries.update_status(delivery_id, status)
        except KeyError:
            return
