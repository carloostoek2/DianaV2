"""AiogramTelegramActuator — TelegramActuatorPort over aiogram Bot."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.enums import ChatAction

from diana.behavior.ports import TelegramActuatorPort

logger = logging.getLogger("diana.telegram")


class AiogramTelegramActuator(TelegramActuatorPort):
    """Business-chat actuator. Always requires business_connection_id."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    def _require_bc(self, business_connection_id: str) -> str:
        bc = (business_connection_id or "").strip()
        if not bc:
            raise ValueError("business_connection_id is required")
        return bc

    async def read_business_message(
        self,
        chat_id: int,
        message_id: int | None,
        *,
        business_connection_id: str,
    ) -> None:
        bc = self._require_bc(business_connection_id)
        if message_id is None:
            return
        await self._bot.read_business_message(
            business_connection_id=bc,
            chat_id=chat_id,
            message_id=message_id,
        )

    async def send_chat_action(
        self,
        chat_id: int,
        action: str,
        *,
        business_connection_id: str,
    ) -> None:
        bc = self._require_bc(business_connection_id)
        chat_action = ChatAction.TYPING if action in {"typing", "Typing"} else action
        await self._bot.send_chat_action(
            chat_id=chat_id,
            action=chat_action,
            business_connection_id=bc,
        )

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        business_connection_id: str,
        parse_mode: str | None = None,
    ) -> int:
        bc = self._require_bc(business_connection_id)
        kwargs = {"chat_id": chat_id, "text": text, "business_connection_id": bc}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        msg = await self._bot.send_message(**kwargs)
        return int(msg.message_id)


__all__ = ["AiogramTelegramActuator"]
