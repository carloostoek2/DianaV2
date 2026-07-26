"""AiogramOwnerNotifier — OwnerNotifierPort over private DM."""

from __future__ import annotations

import logging
from uuid import UUID

from aiogram import Bot

from diana.application.ports import (
    DoctrineNotification,
    DraftNotification,
    EscalationNotification,
)
from diana.application.escalation_labels import label_es_for_tipo
from diana.telegram.keyboards import doctrine_keyboard, draft_keyboard

logger = logging.getLogger("diana.telegram")


class AiogramOwnerNotifier:
    """Owner private-chat notifications (draft / escalate / info)."""

    def __init__(self, bot: Bot, *, owner_telegram_id: int) -> None:
        self._bot = bot
        self._owner_id = owner_telegram_id

    async def notify_draft(self, payload: DraftNotification) -> int | None:
        turn_id = payload.turn_id if isinstance(payload.turn_id, UUID) else UUID(str(payload.turn_id))
        text = (
            f"Draft for chat {payload.chat_id}\n"
            f"VIP: {payload.vip_text}\n"
            f"Draft: {payload.draft_text}\n"
            f"Reason: {payload.reason}"
        )
        if payload.evaluation_summary:
            text += f"\nEval: {payload.evaluation_summary}"
        msg = await self._bot.send_message(
            chat_id=self._owner_id,
            text=text,
            reply_markup=draft_keyboard(turn_id),
        )
        return int(msg.message_id)

    async def notify_escalation(self, payload: EscalationNotification) -> None:
        label = label_es_for_tipo(payload.tipo)
        text = (
            f"Escalación: {label} [{payload.tipo}] turn={payload.turn_id}\n"
            f"chat={payload.chat_id}\n"
            f"reason={payload.reason}"
        )
        if payload.vip_text:
            text += f"\nVIP: {payload.vip_text}"
        await self._bot.send_message(chat_id=self._owner_id, text=text)

    async def notify_doctrine(self, payload: DoctrineNotification) -> int | None:
        """Send a gray zone doctrine query to the owner DM."""
        text = (
            f"[DOCTRINE QUERY] turn={payload.turn_id}\n"
            f"chat={payload.chat_id}\n"
            f"VIP: {payload.vip_text}\n"
            f"Draft: {payload.draft_text or '(no draft)'}\n"
            f"Reason: {payload.reason}"
        )
        if payload.evaluation_summary:
            text += f"\nEval: {payload.evaluation_summary}"
        markup = doctrine_keyboard(turn_id=payload.turn_id)
        msg = await self._bot.send_message(
            chat_id=self._owner_id,
            text=text,
            reply_markup=markup,
        )
        return int(msg.message_id)

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        _ = chat_id
        await self._bot.send_message(chat_id=self._owner_id, text=text)


__all__ = ["AiogramOwnerNotifier"]
