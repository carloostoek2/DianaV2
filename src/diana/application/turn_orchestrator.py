"""TurnOrchestrator — VIP message use-case wiring (supervised F1)."""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from diana.application.admin_service import AdminService
from diana.application.ports import MessageHistoryWriter, VipInboundMessage
from diana.application.turn_coordinator import TurnCoordinator
from diana.cognitive.exceptions import AnalystSchemaInvalidError
from diana.cognitive.models import (
    TERMINAL_TURN_STATUSES,
    Decision,
    IncomingTurn,
    TurnStatus,
    parse_turn_status,
)

logger = logging.getLogger("diana.application")


class DirectorPort(Protocol):
    async def handle_turn(self, turn_context: IncomingTurn) -> Decision: ...


class LearningPort(Protocol):
    async def run_post_turn(self, turn_id: UUID) -> object: ...


def _is_terminal(status: str) -> bool:
    try:
        return parse_turn_status(status) in TERMINAL_TURN_STATUSES
    except ValueError:
        return False


class TurnOrchestrator:
    """Application entry for VIP business messages.

    Mints ``turn_id`` before Director. Never calls Behavior.deliver on approve.
    Holds the per-chat lock for the full use-case so a mid-pipeline supersede
    cannot interleave (zombie-pipeline guard). Terminal latch still applies.
    """

    def __init__(
        self,
        *,
        coordinator: TurnCoordinator,
        director: DirectorPort,
        admin: AdminService,
        learning: LearningPort,
        history: MessageHistoryWriter,
    ) -> None:
        self._coordinator = coordinator
        self._director = director
        self._admin = admin
        self._learning = learning
        self._history = history

    async def handle_vip_message(self, incoming: VipInboundMessage) -> UUID:
        """Process one VIP message; return the minted turn_id."""
        chat_id = incoming.chat_id
        async with self._coordinator.chat_scope(chat_id):
            return await self._handle_vip_message_locked(incoming)

    async def _handle_vip_message_locked(
        self, incoming: VipInboundMessage
    ) -> UUID:
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
                error = "analista_schema_invalido"
                await self._coordinator.mark_failed(turn_id, error=error)
                await self._admin.notify_info(
                    f"Turn {turn_id} failed: analista_schema_invalido",
                    chat_id=incoming.chat_id,
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
        if live is None or _is_terminal(live.status):
            logger.info(
                "orchestrator_aborted_terminal",
                extra={
                    "turn_id": str(turn_id),
                    "status": None if live is None else live.status,
                },
            )
            await self._learning.run_post_turn(turn_id)
            return turn_id

        if decision.action == "approve":
            await self._coordinator.transition(
                turn_id, TurnStatus.PENDING_APPROVAL
            )
            await self._admin.send_draft_for_approval(
                turn_ctx, decision, turn_id
            )
            # CRITICAL: never call behavior.deliver here (L2 / R1)
        elif decision.action == "escalate":
            await self._coordinator.transition(turn_id, TurnStatus.ESCALATED)
            await self._admin.notify_escalation(turn_ctx, decision, turn_id)
        else:
            await self._coordinator.mark_failed(
                turn_id, error=f"unexpected F1 action: {decision.action!r}"
            )
            raise ValueError(f"unexpected F1 action: {decision.action!r}")

        await self._learning.run_post_turn(turn_id)
        logger.info(
            "vip_message_handled",
            extra={
                "turn_id": str(turn_id),
                "chat_id": incoming.chat_id,
                "action": decision.action,
            },
        )
        return turn_id
