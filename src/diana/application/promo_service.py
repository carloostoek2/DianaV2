"""PromoService — exact-match non-VIP promo sequences (no LLM).

F3 proactivity: match trigger → assemble first-send or re-intro sequence →
deliver via BehaviorEngine.deliver_with_sequence → always record promo_executions.

CLARIFY: recent execution never silences; it only swaps the first message
when ``repeat_first_message`` is set.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from diana.application.ports import (
    DeliveryContext,
    DeliveryMode,
    DeliveryResult,
    PromoExecutionStore,
    PromoTriggerRecord,
    PromoTriggerStore,
    TurnRecord,
    TurnStore,
)

logger = logging.getLogger("diana.application")

_DEFAULT_REPEAT_DAYS = 30


class PromoConfigReader(Protocol):
    """Thin config port — ``get_promo_config()`` returns promo JSON blob."""

    async def get_promo_config(self) -> dict[str, Any]: ...


class Clock(Protocol):
    def now(self) -> Any: ...


class SequenceDeliverer(Protocol):
    """Subset of BehaviorEngine used by promo (not BehaviorDeliverer)."""

    async def deliver_with_sequence(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
        decision: Any | None = None,
    ) -> DeliveryResult: ...


class PromoService:
    """Exact-match promo for non-VIP business chats (FEATURE_PROMO_ENABLED)."""

    def __init__(
        self,
        *,
        feature_promo_enabled: bool,
        triggers: PromoTriggerStore,
        executions: PromoExecutionStore,
        config: PromoConfigReader,
        behavior: SequenceDeliverer,
        turns: TurnStore,
        clock: Clock,
        delivery_mode: DeliveryMode = "supervised",
    ) -> None:
        self._feature_promo_enabled = feature_promo_enabled
        self._triggers = triggers
        self._executions = executions
        self._config = config
        self._behavior = behavior
        self._turns = turns
        self._clock = clock
        self._delivery_mode = delivery_mode

    async def match_trigger(self, text: str) -> PromoTriggerRecord | None:
        """Exact case-insensitive match after strip. Empty → None."""
        stripped = (text or "").strip()
        if not stripped:
            return None
        return await self._triggers.get_active_by_trigger_text(stripped)

    async def has_recent_execution(
        self,
        chat_id: int,
        trigger_id: UUID,
        *,
        days: int | None = None,
    ) -> bool:
        """True if a status=sent execution exists within the silence window.

        Window size comes from ``days`` override or ``promo.repeat_days``
        (default 30). Does **not** block delivery — only sequence assembly.
        """
        window = days
        if window is None:
            cfg = await self._config.get_promo_config()
            raw = cfg.get("repeat_days", _DEFAULT_REPEAT_DAYS)
            try:
                window = int(raw)
            except (TypeError, ValueError):
                window = _DEFAULT_REPEAT_DAYS
        if window < 0:
            window = 0
        since = self._clock.now() - timedelta(days=window)
        return await self._executions.was_sent_since(chat_id, trigger_id, since)

    def build_sequence(
        self, trigger: PromoTriggerRecord, *, recent: bool
    ) -> list[str]:
        """Assemble first-send or re-intro sequence (pure).

        Recent + non-empty ``repeat_first_message`` → replace first message;
        otherwise full ``response_sequence``. Never empty-drop for recency.
        """
        sequence = list(trigger.response_sequence or [])
        if not recent:
            return sequence
        reintro = (trigger.repeat_first_message or "").strip()
        if not reintro:
            return sequence
        if not sequence:
            return [reintro]
        return [reintro, *sequence[1:]]

    async def execute_promo(
        self,
        chat_id: int,
        trigger: PromoTriggerRecord,
        *,
        business_connection_id: str,
        telegram_message_id: int | None = None,
    ) -> str:
        """Deliver promo sequence and record execution.

        ``telegram_message_id`` marks the triggering user message as read via
        the engine's read gate (skipped when None).

        Returns: disabled | empty_sequence | sent | failed
        """
        if not self._feature_promo_enabled:
            return "disabled"

        bc = (business_connection_id or "").strip()
        if not bc:
            logger.info(
                "promo_failed",
                extra={"chat_id": chat_id, "reason": "missing_business_connection"},
            )
            return "failed"

        recent = await self.has_recent_execution(chat_id, trigger.id)
        texts = self.build_sequence(trigger, recent=recent)
        if not texts or not any(t.strip() for t in texts):
            logger.info(
                "promo_failed",
                extra={
                    "chat_id": chat_id,
                    "trigger_id": str(trigger.id),
                    "reason": "empty_sequence",
                },
            )
            return "empty_sequence"

        turn = await self._turns.create(
            TurnRecord(
                id=uuid4(),
                chat_id=chat_id,
                status="received",
                vip_id=None,
            )
        )
        ctx = DeliveryContext(
            chat_id=chat_id,
            business_connection_id=bc,
            vip_id=None,
            mode=self._delivery_mode,
            is_frozen=False,
            parse_mode="HTML",
            telegram_message_id=telegram_message_id,
        )

        try:
            result = await self._behavior.deliver_with_sequence(
                texts, ctx, turn.id
            )
        except Exception as exc:
            logger.exception(
                "promo_failed",
                extra={
                    "chat_id": chat_id,
                    "trigger_id": str(trigger.id),
                    "turn_id": str(turn.id),
                },
            )
            await self._executions.insert(
                chat_id, trigger.id, texts, status="failed"
            )
            await self._turns.transition(turn.id, "failed", error=str(exc))
            return "failed"

        status = "sent" if result.success else "failed"
        await self._executions.insert(chat_id, trigger.id, texts, status=status)
        await self._turns.transition(
            turn.id,
            "delivered" if result.success else "failed",
            error=result.error,
        )
        if result.success:
            logger.info(
                "promo_executed",
                extra={
                    "chat_id": chat_id,
                    "trigger_id": str(trigger.id),
                    "turn_id": str(turn.id),
                    "recent": recent,
                    "n_texts": len(texts),
                },
            )
        else:
            logger.info(
                "promo_failed",
                extra={
                    "chat_id": chat_id,
                    "trigger_id": str(trigger.id),
                    "turn_id": str(turn.id),
                    "error": result.error,
                },
            )
        return status


__all__ = ["Clock", "PromoConfigReader", "PromoService", "SequenceDeliverer"]
