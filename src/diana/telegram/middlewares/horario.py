"""HorarioAtencionMiddleware — fuera de la ventana, el VIP no recibe nada (§4.27).

Se registra entre ``AuthMiddleware`` y ``ForbiddenKeywordsMiddleware``:

- después de Auth ya existen ``vip_id`` y ``channel_type``;
- antes de Forbidden porque ese corto-circuito **envía** plantilla y escala al
  instante (precio/pago/identidad). Fuera de horario no debe salir nada al VIP.

Qué hace cuando la ventana está cerrada: guarda el mensaje en el historial del
chat (no es una métrica) y corta la cadena. No crea turno, no deja traza, no
toca confianza, no marca leído — y por eso no ensucia ningún número.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from diana.telegram.media_tags import inbound_text

logger = logging.getLogger("diana.telegram")


@runtime_checkable
class HorarioPort(Protocol):
    """Quien sabe si la ventana está abierta (``HorarioAtencionService``)."""

    async def esta_abierto(self, ahora: datetime) -> bool: ...


@runtime_checkable
class HistorialPort(Protocol):
    """Escritura del historial del chat (rol ``vip``)."""

    async def append(
        self,
        chat_id: int,
        *,
        role: str,
        text: str,
        telegram_message_id: int | None = None,
    ) -> None: ...


class HorarioAtencionMiddleware(BaseMiddleware):
    """Corta los mensajes VIP que llegan fuera de la ventana de atención."""

    def __init__(
        self,
        *,
        horario: HorarioPort,
        history: HistorialPort,
        enabled: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._horario = horario
        self._history = history
        self._enabled = enabled
        self._clock = clock or (lambda: datetime.now(UTC))

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self._enabled:
            return await handler(event, data)
        if not isinstance(event, Message):
            return await handler(event, data)
        if not self._aplica(data):
            return await handler(event, data)

        ahora = self._clock()
        try:
            abierto = await self._horario.esta_abierto(ahora)
        except Exception:
            # Fail-open: un fallo del ajuste no puede dejar a todos los VIP
            # sin respuesta (AGENTS §4.27).
            logger.exception("horario_check_failed")
            abierto = True
        if abierto:
            return await handler(event, data)

        await self._guardar(event, data)
        logger.info(
            "horario_fuera_de_atencion",
            extra={
                "chat_id": getattr(getattr(event, "chat", None), "id", None),
                "telegram_message_id": getattr(event, "message_id", None),
                "es_edicion": getattr(event, "edit_date", None) is not None,
            },
        )
        return None

    def _aplica(self, data: dict[str, Any]) -> bool:
        """Solo chats VIP reales: ni privados de la dueña, ni sandbox, ni Atención."""
        if data.get("sandbox_active"):
            return False
        if data.get("channel_type") == "atencion":
            return False
        if data.get("vip_id") is None:
            return False
        # Los mensajes privados (el panel de la dueña) no traen conexión de
        # negocios; solo los chats de VIP son business messages.
        return bool(data.get("business_connection_id"))

    async def _guardar(self, event: Message, data: dict[str, Any]) -> None:
        """Guarda el mensaje para poder retomarlo al abrir (best-effort)."""
        texto = inbound_text(event)
        if not texto:
            return
        chat = getattr(event, "chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            return
        message_id = getattr(event, "message_id", None)
        try:
            # ``upsert_vip_message`` es idempotente por telegram_message_id: la
            # edición reemplaza y un reintento no duplica. Si el historial no lo
            # expone, se cae al append simple.
            upsert = getattr(self._history, "upsert_vip_message", None)
            if callable(upsert) and message_id is not None:
                await upsert(chat_id, text=texto, telegram_message_id=message_id)
            else:
                await self._history.append(
                    chat_id,
                    role="vip",
                    text=texto,
                    telegram_message_id=message_id,
                )
        except Exception:
            logger.exception(
                "horario_history_write_failed",
                extra={"chat_id": chat_id, "vip_id": data.get("vip_id")},
            )


__all__ = ["HorarioAtencionMiddleware", "HorarioPort", "HistorialPort"]
