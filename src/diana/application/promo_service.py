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
# Stored on pending_deliveries.decision so restart recovery can resume promos.
PROMO_DECISION_KIND = "promo"


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
        feature_general_mode_enabled: bool = False,
    ) -> None:
        self._feature_promo_enabled = feature_promo_enabled
        self._feature_general_mode_enabled = feature_general_mode_enabled
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
                status="promo_pending",
                vip_id=None,
                # Promo targets non-VIP business chats: under general mode the
                # promo turn belongs to the atencion channel. Flag OFF keeps
                # the legacy default (vip) byte-identical.
                channel_type="atencion" if self._feature_general_mode_enabled else "vip",
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
        decision = {
            "kind": PROMO_DECISION_KIND,
            "trigger_id": str(trigger.id),
            "recent": recent,
        }

        try:
            result = await self._behavior.deliver_with_sequence(
                texts, ctx, turn.id, decision=decision
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
            await self._record_outcome(
                chat_id=chat_id,
                trigger_id=trigger.id,
                texts=texts,
                turn_id=turn.id,
                success=False,
                error=str(exc),
            )
            return "failed"

        await self._record_outcome(
            chat_id=chat_id,
            trigger_id=trigger.id,
            texts=texts,
            turn_id=turn.id,
            success=result.success,
            error=result.error,
            recent=recent,
        )
        return "sent" if result.success else "failed"

    async def finalize_recovered_delivery(
        self,
        *,
        chat_id: int,
        turn_id: UUID,
        texts: list[str],
        decision: dict[str, Any] | None,
        result: DeliveryResult,
    ) -> None:
        """Bookkeeping after restart resume of a promo delivery (timer or classify)."""
        if not isinstance(decision, dict) or decision.get("kind") != PROMO_DECISION_KIND:
            return
        raw_tid = decision.get("trigger_id")
        try:
            trigger_id = UUID(str(raw_tid))
        except (TypeError, ValueError):
            logger.warning(
                "promo_recovery_missing_trigger_id",
                extra={"chat_id": chat_id, "turn_id": str(turn_id)},
            )
            await self._turns.transition(
                turn_id,
                "failed" if not result.success else "delivered",
                error=result.error or "promo_recovery_missing_trigger_id",
            )
            return
        await self._record_outcome(
            chat_id=chat_id,
            trigger_id=trigger_id,
            texts=list(texts),
            turn_id=turn_id,
            success=result.success,
            error=result.error,
            recent=bool(decision.get("recent")),
            recovered=True,
        )

    async def _record_outcome(
        self,
        *,
        chat_id: int,
        trigger_id: UUID,
        texts: list[str],
        turn_id: UUID,
        success: bool,
        error: str | None = None,
        recent: bool = False,
        recovered: bool = False,
    ) -> None:
        status = "sent" if success else "failed"
        await self._executions.insert(chat_id, trigger_id, texts, status=status)
        await self._turns.transition(
            turn_id,
            "delivered" if success else "failed",
            error=error,
        )
        event = "promo_executed" if success else "promo_failed"
        if recovered:
            event = "promo_recovered_sent" if success else "promo_recovered_failed"
        extra: dict[str, Any] = {
            "chat_id": chat_id,
            "trigger_id": str(trigger_id),
            "turn_id": str(turn_id),
            "n_texts": len(texts),
            "recent": recent,
        }
        if not success:
            extra["error"] = error
        logger.info(event, extra=extra)


__all__ = [
    "Clock",
    "PROMO_DECISION_KIND",
    "PromoConfigReader",
    "PromoService",
    "SequenceDeliverer",
]
