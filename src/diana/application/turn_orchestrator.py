"""TurnOrchestrator — VIP message use-case wiring (supervised + autonomous send)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from diana.application.admin_service import AdminService
from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.gray_zone_service import GrayZoneService
from diana.application.observability import log_swallowed
from diana.application.ports import (
    BehaviorDeliverer,
    DeliveryContext,
    DeliveryMode,
    DeliveryResult,
    DeliveryResultWriter,
    MessageHistoryWriter,
    VipInboundMessage,
    VipStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.exceptions import (
    AnalystSchemaInvalidError,
    ContextExceedsLimitError,
    EvaluatorSchemaInvalidError,
    GeneratorEmptyOutputError,
)
from diana.cognitive.models import (
    Decision,
    IncomingTurn,
    TurnStatus,
    is_turn_status_terminal,
)

logger = logging.getLogger("diana.application")


class DirectorPort(Protocol):
    async def handle_turn(self, turn_context: IncomingTurn) -> Decision: ...


class LearningPort(Protocol):
    async def run_post_turn(self, turn_id: UUID) -> object: ...


@dataclass(frozen=True, slots=True)
class _AutonomousDeliverJob:
    """Prepared autonomous deliver payload — executed outside chat_scope."""

    text: str
    ctx: DeliveryContext
    decision: Decision


class TurnOrchestrator:
    """Application entry for VIP business messages.

    Supervised approve never auto-delivers. Autonomous ``action=="send"``
    delivers via BehaviorEngine **outside** the per-chat lock so
    cancel_pending can interrupt mid-flight (Admin pattern).
    """

    def __init__(
        self,
        *,
        coordinator: TurnCoordinator,
        director: DirectorPort,
        admin: AdminService,
        learning: LearningPort,
        history: MessageHistoryWriter,
        gray_zone: GrayZoneService | None = None,
        feature_gray_zone_enabled: bool = False,
        behavior: BehaviorDeliverer | None = None,
        autonomous_mode: AutonomousModeService | None = None,
        vip_store: VipStore | None = None,
        traces: DeliveryResultWriter | None = None,
        delivery_mode: DeliveryMode = "supervised",
        feature_advanced_behavior: bool = False,
    ) -> None:
        self._coordinator = coordinator
        self._director = director
        self._admin = admin
        self._learning = learning
        self._history = history
        self._gray_zone = gray_zone
        self._feature_gray_zone_enabled = feature_gray_zone_enabled
        self._behavior = behavior
        self._autonomous_mode = autonomous_mode
        self._vip_store = vip_store
        self._traces = traces
        self._delivery_mode = delivery_mode
        self._feature_advanced_behavior = bool(feature_advanced_behavior)

    async def _safe_notify_info(
        self,
        message: str,
        *,
        chat_id: int,
        event: str,
        **extra: object,
    ) -> None:
        """Owner notify fail-soft: never mask the primary failure path."""
        try:
            await self._admin.notify_info(message, chat_id=chat_id)
        except Exception:
            log_swallowed(logger, event, chat_id=chat_id, **extra)

    async def _fail_director_typed(
        self,
        turn_id: UUID,
        chat_id: int,
        *,
        error: str,
        notify_event: str,
    ) -> None:
        """mark_failed then fail-soft owner notify (typed director errors)."""
        await self._coordinator.mark_failed(turn_id, error=error)
        await self._safe_notify_info(
            f"Turn {turn_id} failed: {error}",
            chat_id=chat_id,
            event=notify_event,
            turn_id=str(turn_id),
        )

    async def handle_vip_message(self, incoming: VipInboundMessage) -> UUID:
        """Process one VIP message; return the minted turn_id."""
        chat_id = incoming.chat_id
        pending_deliver: _AutonomousDeliverJob | None
        async with self._coordinator.chat_scope(chat_id):
            turn_id, pending_deliver = await self._handle_vip_message_locked(
                incoming
            )
            if pending_deliver is None:
                await self._learning.run_post_turn(turn_id)
                return turn_id

        # OUTSIDE lock — cancel_pending can interrupt delays (Admin pattern).
        # Re-check freeze after lock release (race: freeze applied mid-pipeline).
        vip_frozen = await self._is_vip_frozen(incoming.vip_id)
        if vip_frozen:
            async with self._coordinator.chat_scope(chat_id):
                live = await self._coordinator.get_turn(turn_id)
                if live is not None and not is_turn_status_terminal(live.status):
                    await self._coordinator.mark_failed(
                        turn_id, error="vip_frozen"
                    )
                    await self._safe_notify_info(
                        f"Turn {turn_id} failed: vip_frozen",
                        chat_id=chat_id,
                        event="owner_notify_failed_after_vip_frozen",
                        turn_id=str(turn_id),
                    )
            await self._learning.run_post_turn(turn_id)
            logger.info(
                "autonomous_vip_frozen_pre_deliver",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": chat_id,
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            return turn_id

        # Prepare already fails closed if behavior is None; re-check for
        # partial wiring / race without relying on assert (stripped under -O).
        if self._behavior is None:
            async with self._coordinator.chat_scope(chat_id):
                live = await self._coordinator.get_turn(turn_id)
                if live is not None and not is_turn_status_terminal(live.status):
                    await self._coordinator.mark_failed(
                        turn_id, error="autonomous_behavior_not_wired"
                    )
            await self._learning.run_post_turn(turn_id)
            logger.error(
                "autonomous_behavior_not_wired",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return turn_id

        # SEC-F2: pass actual freeze snapshot from re-check (False after gate).
        # Mid-delay FreezePort re-query remains residual (engine uses ctx only).
        deliver_ctx = pending_deliver.ctx.model_copy(
            update={"is_frozen": vip_frozen}
        )
        logger.info(
            "autonomous_send_start",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
            },
        )
        result = await self._behavior.deliver(
            [pending_deliver.text],
            deliver_ctx,
            turn_id,
            decision=pending_deliver.decision,
        )
        async with self._coordinator.chat_scope(chat_id):
            delivered = await self._finalize_autonomous_delivery(
                turn_id, chat_id, result
            )

        # Near-threshold notify only when finalize confirmed DELIVERED
        # (not raw actuator success — mid-flight supersede must not notify).
        if (
            delivered
            and self._autonomous_mode is not None
        ):
            await self._autonomous_mode.notify_if_needed(
                turn_id,
                pending_deliver.decision,
                pending_deliver.decision.evaluation,
            )

        await self._learning.run_post_turn(turn_id)
        logger.info(
            "vip_message_handled",
            extra={
                "turn_id": str(turn_id),
                "chat_id": chat_id,
                "action": "send",
            },
        )
        return turn_id

    async def _handle_vip_message_locked(
        self, incoming: VipInboundMessage
    ) -> tuple[UUID, _AutonomousDeliverJob | None]:
        bc = incoming.business_connection_id
        if bc is None or not str(bc).strip():
            record = await self._coordinator.begin_turn_unlocked(
                chat_id=incoming.chat_id,
                trigger_message_id=incoming.telegram_message_id,
                vip_id=incoming.vip_id,
            )
            await self._coordinator.mark_failed(
                record.id, error="business_connection_id is required"
            )
            raise ValueError("business_connection_id is required")

        record = await self._coordinator.begin_turn_unlocked(
            chat_id=incoming.chat_id,
            trigger_message_id=incoming.telegram_message_id,
            vip_id=incoming.vip_id,
        )
        turn_id = record.id

        await self._history.append(
            incoming.chat_id,
            role="vip",
            text=incoming.text,
            telegram_message_id=incoming.telegram_message_id,
        )

        turn_ctx = IncomingTurn(
            turn_id=turn_id,
            chat_id=incoming.chat_id,
            vip_id=incoming.vip_id,
            text=incoming.text,
            telegram_message_id=incoming.telegram_message_id,
            business_connection_id=str(bc).strip(),
        )

        try:
            decision = await self._director.handle_turn(turn_ctx)
        except Exception as exc:
            # Terminal latch: no-ops if already superseded while Director ran
            # (should not happen under full chat_scope; still safe).
            # A.6 Analyst schema fail: stable reason + owner notify (no VIP send).
            if isinstance(exc, AnalystSchemaInvalidError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="analista_schema_invalido",
                    notify_event="owner_notify_failed_after_analyst_schema_invalid",
                )
            elif isinstance(exc, EvaluatorSchemaInvalidError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="evaluador_schema_invalido",
                    notify_event="owner_notify_failed_after_evaluator_schema_invalid",
                )
            elif isinstance(exc, ContextExceedsLimitError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="contexto_excede_limite",
                    notify_event="owner_notify_failed_after_context_exceeds_limit",
                )
            elif isinstance(exc, GeneratorEmptyOutputError):
                await self._fail_director_typed(
                    turn_id,
                    incoming.chat_id,
                    error="generador_salida_vacia",
                    notify_event="owner_notify_failed_after_generator_empty_output",
                )
            else:
                await self._coordinator.mark_failed(turn_id, error=str(exc))
            logger.exception(
                "director_failed",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            raise

        # Post-Director liveness check (defense in depth vs zombie pipeline).
        live = await self._coordinator.get_turn(turn_id)
        if live is None or is_turn_status_terminal(live.status):
            logger.info(
                "orchestrator_aborted_terminal",
                extra={
                    "turn_id": str(turn_id),
                    "status": None if live is None else live.status,
                },
            )
            return turn_id, None

        if decision.action == "approve":
            await self._coordinator.transition(
                turn_id, TurnStatus.PENDING_APPROVAL
            )
            await self._admin.send_draft_for_approval(
                turn_ctx, decision, turn_id
            )
            # CRITICAL: never call behavior.deliver here (L2 / R1)
        elif decision.action == "consult_doctrine":
            if not self._feature_gray_zone_enabled:
                raise RuntimeError(
                    "consult_doctrine action returned but gray zone feature is disabled"
                )
            if self._gray_zone is None:
                raise RuntimeError(
                    "consult_doctrine action returned but GrayZoneService is not injected"
                )
            if turn_ctx.vip_id is None:
                raise RuntimeError(
                    "consult_doctrine requires vip_id but turn has None"
                )
            # Create query + notify BEFORE transitioning to GRAY_ZONE so
            # a failure does not leave the turn stuck in gray_zone (BUG-3).
            query = await self._gray_zone.create_query(
                vip_id=turn_ctx.vip_id,
                turn_id=turn_id,
                question=turn_ctx.text,
                draft=decision.draft_text or "",
            )
            await self._admin.send_doctrine_query(
                turn_ctx, decision, turn_id, query
            )
            await self._coordinator.transition(
                turn_id, TurnStatus.GRAY_ZONE
            )
            logger.info(
                "consult_doctrine_completed",
                extra={
                    "turn_id": str(turn_id),
                    "vip_id": str(turn_ctx.vip_id),
                    "query_id": str(query.id) if hasattr(query, "id") else None,
                },
            )
            # CRITICAL: never call behavior.deliver — VIP is frozen
        elif decision.action == "escalate":
            await self._coordinator.transition(turn_id, TurnStatus.ESCALATED)
            await self._admin.notify_escalation(turn_ctx, decision, turn_id)
        elif decision.action == "send":
            job = await self._prepare_autonomous_send(
                turn_id=turn_id,
                turn_ctx=turn_ctx,
                decision=decision,
                incoming=incoming,
            )
            if job is not None:
                return turn_id, job
        else:
            logger.error(
                "unexpected_f2_action",
                extra={
                    "turn_id": str(turn_id),
                    "action": decision.action,
                    "chat_id": incoming.chat_id,
                },
            )
            await self._coordinator.mark_failed(
                turn_id, error=f"unexpected F2 action: {decision.action!r}"
            )
            raise ValueError(f"unexpected F2 action: {decision.action!r}")

        logger.info(
            "vip_message_handled",
            extra={
                "turn_id": str(turn_id),
                "chat_id": incoming.chat_id,
                "action": decision.action,
            },
        )
        return turn_id, None

    async def _prepare_autonomous_send(
        self,
        *,
        turn_id: UUID,
        turn_ctx: IncomingTurn,
        decision: Decision,
        incoming: VipInboundMessage,
    ) -> _AutonomousDeliverJob | None:
        """Gate AMS + frozen/empty; return deliver job or complete under lock."""
        if self._autonomous_mode is None:
            logger.error(
                "autonomous_not_wired",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": incoming.chat_id,
                },
            )
            await self._coordinator.mark_failed(
                turn_id, error="autonomous_not_wired"
            )
            return None

        enabled = await self._autonomous_mode.is_autonomous_enabled(
            incoming.vip_id
        )
        if not enabled:
            logger.info(
                "autonomous_disabled_for_vip",
                extra={
                    "turn_id": str(turn_id),
                    "chat_id": incoming.chat_id,
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            # Demote send → approve with explicit reason (not autonomous_ok).
            demoted = decision.model_copy(
                update={
                    "action": "approve",
                    "reason": "autonomous_mode_disabled",
                }
            )
            await self._coordinator.transition(
                turn_id, TurnStatus.PENDING_APPROVAL
            )
            await self._admin.send_draft_for_approval(
                turn_ctx, demoted, turn_id
            )
            return None

        if await self._is_vip_frozen(incoming.vip_id):
            logger.info(
                "autonomous_vip_frozen",
                extra={
                    "turn_id": str(turn_id),
                    "vip_id": str(incoming.vip_id) if incoming.vip_id else None,
                },
            )
            await self._coordinator.mark_failed(turn_id, error="vip_frozen")
            await self._safe_notify_info(
                f"Turn {turn_id} failed: vip_frozen",
                chat_id=incoming.chat_id,
                event="owner_notify_failed_after_vip_frozen",
                turn_id=str(turn_id),
            )
            return None

        draft = (decision.draft_text or "").strip()
        if not draft:
            logger.info(
                "autonomous_empty_draft",
                extra={"turn_id": str(turn_id), "chat_id": incoming.chat_id},
            )
            await self._coordinator.mark_failed(turn_id, error="empty_draft")
            await self._safe_notify_info(
                f"Turn {turn_id} failed: empty_draft",
                chat_id=incoming.chat_id,
                event="owner_notify_failed_after_empty_draft",
                turn_id=str(turn_id),
            )
            return None

        if self._behavior is None:
            logger.error(
                "autonomous_behavior_not_wired",
                extra={"turn_id": str(turn_id)},
            )
            await self._coordinator.mark_failed(
                turn_id, error="autonomous_behavior_not_wired"
            )
            return None

        # is_frozen=False: prepare only builds a job when VIP is not frozen.
        # Engine hard-check of is_frozen is defense-in-depth; orch re-checks
        # after lock release before deliver.
        advanced = self._feature_advanced_behavior
        ctx = DeliveryContext(
            chat_id=incoming.chat_id,
            business_connection_id=str(turn_ctx.business_connection_id).strip(),
            vip_id=incoming.vip_id,
            telegram_message_id=incoming.telegram_message_id,
            mode=self._delivery_mode,
            is_frozen=False,
            allow_split=advanced,
            allow_human_quirks=advanced,
            split_chars=4096,
        )
        return _AutonomousDeliverJob(text=draft, ctx=ctx, decision=decision)

    async def _is_vip_frozen(self, vip_id: UUID | None) -> bool:
        """True if vip_store says frozen_until > now(UTC). Missing store/id → False."""
        if self._vip_store is None or vip_id is None:
            return False
        vip = await self._vip_store.get_by_id(vip_id)
        if vip is None or vip.frozen_until is None:
            return False
        now = datetime.now(UTC)
        frozen = vip.frozen_until
        if frozen.tzinfo is None:
            frozen = frozen.replace(tzinfo=UTC)
        return frozen > now

    async def _finalize_autonomous_delivery(
        self,
        turn_id: UUID,
        chat_id: int,
        result: DeliveryResult,
    ) -> bool:
        """Post-deliver terminal check under chat lock (Admin I.5 parity, no approval).

        Returns True only when the turn was transitioned to DELIVERED.
        Not a SQL CAS / claim token — single-process lock + terminal latch.
        """
        turn_after = await self._coordinator.get_turn(turn_id)
        if turn_after is None or is_turn_status_terminal(turn_after.status):
            logger.info(
                "autonomous_aborted_terminal_after_deliver",
                extra={
                    "turn_id": str(turn_id),
                    "status": None if turn_after is None else turn_after.status,
                    "deliver_success": result.success,
                },
            )
            return False

        if result.success:
            await self._coordinator.transition(turn_id, TurnStatus.DELIVERED)
            if self._traces is not None:
                await self._traces.set_delivery_result(
                    turn_id, result.to_trace_dict()
                )
            logger.info(
                "autonomous_delivered",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return True

        if result.cancelled:
            await self._coordinator.mark_failed(
                turn_id, error=result.error or "delivery_cancelled"
            )
            if self._traces is not None:
                await self._traces.set_delivery_result(
                    turn_id, result.to_trace_dict()
                )
            logger.info(
                "autonomous_deliver_cancelled",
                extra={
                    "turn_id": str(turn_id),
                    "error": result.error,
                },
            )
            return False

        # Permanent deliver failure (I.5).
        await self._coordinator.mark_failed(
            turn_id, error=result.error or "delivery_failed"
        )
        await self._safe_notify_info(
            f"Turn {turn_id} failed: delivery_failed ({result.error})",
            chat_id=chat_id,
            event="owner_notify_failed_after_autonomous_deliver_fail",
            turn_id=str(turn_id),
        )
        if self._traces is not None:
            await self._traces.set_delivery_result(
                turn_id, result.to_trace_dict()
            )
        logger.info(
            "autonomous_deliver_failed",
            extra={"turn_id": str(turn_id), "error": result.error},
        )
        return False
