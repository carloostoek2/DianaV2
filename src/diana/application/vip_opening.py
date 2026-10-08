"""Arranque de conversación de un VIP recién dado de alta.

Producto: la dueña agrega a alguien que ya le había escrito —a veces con fotos
o videos— y esos mensajes quedaron sin responder porque el bot todavía no lo
conocía. Este servicio toma los últimos mensajes sin responder del historial
importado y arma el turno, que termina en el borrador de la cola de aprobación
de la dueña.

Nunca envía nada por su cuenta: el único destino posible es la cola de
aprobación. Un VIP con envío automático activado queda fuera del arranque, para
que un mensaje viejo no se dispare solo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from diana.application.ports import (
    BusinessConnectionRecord,
    VipInboundMessage,
    VipRecord,
)
from diana.application.turn_orchestrator import format_vip_burst_text

logger = logging.getLogger("diana.application")

# Ventana de historial que se lee para encontrar los mensajes sin responder.
_HISTORY_WINDOW = 40
# Tope de mensajes que se contestan de una sola vez en el arranque.
_DEFAULT_MAX_MESSAGES = 3

OpeningKind = Literal["started", "skipped"]


@dataclass(frozen=True, slots=True)
class OpeningOutcome:
    """Resultado de un intento de arranque (para el aviso a la dueña y los logs)."""

    kind: OpeningKind
    reason: str | None = None
    turn_id: UUID | None = None
    messages: int = 0


@runtime_checkable
class VipTurnRunner(Protocol):
    """Arranca un turno VIP con un mensaje de entrada (lo implementa el orquestador)."""

    async def handle_vip_message(self, incoming: VipInboundMessage) -> UUID: ...


@runtime_checkable
class RecentHistoryReader(Protocol):
    """Lectura del historial reciente de un chat."""

    async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]: ...


@runtime_checkable
class VipLookup(Protocol):
    """Alta de VIP consultada por su identificador de Telegram."""

    async def get_record_and_allowed(self, telegram_user_id: int) -> VipRecord | None: ...


@runtime_checkable
class ConnectionLookup(Protocol):
    """Conexión de negocios vigente de la cuenta de la dueña."""

    async def get_active(self) -> BusinessConnectionRecord | None: ...


@runtime_checkable
class NonTerminalTurnReader(Protocol):
    """Turnos vivos de un chat (para no pisar una conversación en curso)."""

    async def list_non_terminal(self, chat_id: int) -> list[object]: ...


class VipOpeningService:
    """Arma el arranque de conversación de un VIP nuevo."""

    def __init__(
        self,
        *,
        runner: VipTurnRunner,
        history: RecentHistoryReader,
        vips: VipLookup,
        connections: ConnectionLookup,
        coordinator: NonTerminalTurnReader,
        max_messages: int = _DEFAULT_MAX_MESSAGES,
    ) -> None:
        self._runner = runner
        self._history = history
        self._vips = vips
        self._connections = connections
        self._coordinator = coordinator
        self._max_messages = max(1, int(max_messages))

    async def start(self, telegram_user_id: int) -> OpeningOutcome:
        """Arranca la conversación, o explica por qué no corresponde."""
        chat_id = int(telegram_user_id)
        record = await self._vips.get_record_and_allowed(chat_id)
        if record is None:
            return self._skip(chat_id, "vip_unknown")
        if bool(getattr(record, "auto_send", False)):
            # El arranque siempre termina en la cola de aprobación; con envío
            # automático activado no se arranca para no disparar solo.
            return self._skip(chat_id, "auto_send_enabled")
        live = await self._coordinator.list_non_terminal(chat_id)
        if live:
            # Un solo turno vivo por chat: si la conversación ya está en curso,
            # no se mete de prepo.
            return self._skip(chat_id, "chat_busy")

        burst = await self._unanswered(chat_id)
        if not burst:
            return self._skip(chat_id, "nothing_to_answer")

        connection = await self._connections.get_active()
        if connection is None:
            # Sin conexión vigente no hay forma de responder en ese chat.
            return self._skip(chat_id, "no_business_connection")

        last = burst[-1]
        incoming = VipInboundMessage(
            chat_id=chat_id,
            text=format_vip_burst_text(
                [row["text"] for row in burst], fallback=burst[-1]["text"]
            ),
            telegram_message_id=last.get("telegram_message_id"),
            business_connection_id=connection.business_connection_id,
            vip_id=record.id,
            channel_type="vip",
            # El texto ya viene unido y acotado desde aquí.
            skip_coalesce=True,
        )
        turn_id = await self._runner.handle_vip_message(incoming)
        logger.info(
            "vip_opening_started",
            extra={
                "chat_id": chat_id,
                "turn_id": str(turn_id),
                "messages": len(burst),
            },
        )
        return OpeningOutcome(kind="started", turn_id=turn_id, messages=len(burst))

    async def _unanswered(self, chat_id: int) -> list[dict]:
        """Últimos mensajes del VIP sin responder, en orden cronológico."""
        try:
            rows = await self._history.get_recent(chat_id, limit=_HISTORY_WINDOW)
        except Exception:
            logger.exception("vip_opening_history_read_failed", extra={"chat_id": chat_id})
            return []
        trailing: list[dict] = []
        for row in rows:  # get_recent devuelve del más nuevo al más viejo
            if not isinstance(row, dict) or row.get("role") != "vip":
                break
            if not str(row.get("text") or "").strip():
                continue
            trailing.append(row)
        selected = list(reversed(trailing[: self._max_messages]))
        return selected

    def _skip(self, chat_id: int, reason: str) -> OpeningOutcome:
        logger.info("vip_opening_skipped", extra={"chat_id": chat_id, "reason": reason})
        return OpeningOutcome(kind="skipped", reason=reason)


__all__ = [
    "ConnectionLookup",
    "NonTerminalTurnReader",
    "OpeningOutcome",
    "RecentHistoryReader",
    "VipLookup",
    "VipOpeningService",
    "VipTurnRunner",
]
