"""AiogramOwnerNotifier — OwnerNotifierPort over private DM."""

from __future__ import annotations

import logging
from uuid import UUID

from aiogram import Bot

from diana.application.ports import (
    DoctrineNotification,
    DraftNotification,
    EscalationNotification,
    LinkNotification,
)
from diana.application.escalation_labels import label_es_for_tipo
from diana.application.draft_variants import format_draft_owner_text, read_versions
from diana.telegram.keyboards import (
    doctrine_keyboard,
    draft_keyboard,
    escalation_keyboard,
    link_kick_keyboard,
)

logger = logging.getLogger("diana.telegram")


def _esc(text: str) -> str:
    """Escape text for Telegram HTML parse_mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class AiogramOwnerNotifier:
    """Owner private-chat notifications (draft / escalate / info)."""

    def __init__(self, bot: Bot, *, owner_telegram_id: int) -> None:
        self._bot = bot
        self._owner_id = owner_telegram_id

    async def notify_draft(self, payload: DraftNotification) -> int | None:
        turn_id = payload.turn_id if isinstance(payload.turn_id, UUID) else UUID(str(payload.turn_id))
        name = payload.vip_display_name or str(payload.chat_id)
        versions = read_versions(payload.evaluation)
        items = versions.get("items") or []
        selected = int(versions.get("selected") or 0)
        count = max(len(items), 1)
        text = format_draft_owner_text(
            vip_name=name,
            vip_text=payload.vip_text,
            draft_text=payload.draft_text,
            reason=payload.reason or "",
            evaluation_summary=payload.evaluation_summary or "",
            version_index=selected if items else 0,
            version_count=count,
        )
        msg = await self._bot.send_message(
            chat_id=self._owner_id,
            text=text,
            reply_markup=draft_keyboard(
                turn_id,
                chat_id=payload.chat_id,
                show_quality_feedback=payload.show_quality_feedback,
            ),
            parse_mode="HTML",
        )
        return int(msg.message_id)

    async def edit_draft(
        self,
        *,
        owner_message_id: int,
        text: str,
        turn_id: UUID,
        chat_id: int,
        show_quality_feedback: bool = False,
    ) -> None:
        """Update the existing owner draft message in place (regen / prev / next)."""
        await self._bot.edit_message_text(
            chat_id=self._owner_id,
            message_id=owner_message_id,
            text=text,
            reply_markup=draft_keyboard(
                turn_id,
                chat_id=chat_id,
                show_quality_feedback=show_quality_feedback,
            ),
            parse_mode="HTML",
        )

    async def void_draft(self, *, owner_message_id: int, text: str) -> None:
        """Mark a draft DM as cancelled, keep the draft body, remove inline buttons."""
        await self._bot.edit_message_text(
            chat_id=self._owner_id,
            message_id=owner_message_id,
            text=text,
            reply_markup=None,
            parse_mode="HTML",
        )

    async def notify_escalation(self, payload: EscalationNotification) -> None:
        label = label_es_for_tipo(payload.tipo)
        text = (
            f"Escalación: {label} [{payload.tipo}] turn={payload.turn_id}\n"
            f"chat={payload.chat_id}\n"
            f"reason={payload.reason}"
        )
        if payload.vip_text:
            text += f"\nVIP: {payload.vip_text}"
        await self._bot.send_message(
            chat_id=self._owner_id,
            text=text,
            reply_markup=escalation_keyboard(payload.turn_id),
        )

    async def notify_doctrine(self, payload: DoctrineNotification) -> int | None:
        """Send a gray zone doctrine query to the owner DM (asks for a RULE).

        Layout (AGENTS §4.5): the ORIGINAL message of the turn is shown first,
        clearly labeled as CONTEXT; then, when a system proposal exists, the
        "Propuesta del sistema" block (rule + suggested reply) as a SUGGESTION
        only — the owner decides; then the action buttons.
        """
        text = (
            f"🧭 Consulta de doctrina — turno {payload.turn_id}\n"
            f"Chat: {payload.chat_id}\n"
            f"Motivo: {payload.reason}\n\n"
            "📩 Mensaje original (contexto):\n"
            f"{payload.vip_text or '(sin texto)'}"
        )
        if payload.draft_text:
            text += f"\n\n🤖 Borrador generado por Diana (solo contexto):\n{payload.draft_text}"
        if payload.proposed_rule:
            text += (
                "\n\n💡 Propuesta del sistema (sugerencia, revise antes de usar):\n"
                f"Regla propuesta: {payload.proposed_rule}"
            )
            if payload.proposed_reply:
                text += f"\nRespuesta sugerida: {payload.proposed_reply}"
            text += (
                "\n\n'Usar regla propuesta' adopta la REGLA sugerida (no el mensaje); "
                "Diana regenerará el borrador y lo enviará a tu aprobación."
            )
        else:
            text += (
                "\n\nEscribe una REGLA / norma de negocio (no el texto que recibirá el "
                "VIP). Diana regenerará el borrador con esa regla y te lo mandará a aprobar."
            )
        if payload.evaluation_summary:
            text += f"\nEval: {payload.evaluation_summary}"
        markup = doctrine_keyboard(
            turn_id=payload.turn_id, has_proposal=bool(payload.proposed_rule)
        )
        msg = await self._bot.send_message(
            chat_id=self._owner_id,
            text=text,
            reply_markup=markup,
        )
        return int(msg.message_id)

    async def notify_link(self, payload: LinkNotification) -> int | None:
        """Send the kicked-VIP Expel/Disable/Keep notification to the owner DM."""
        name = payload.display_name
        if payload.username:
            name = f"{name} @{payload.username.lstrip('@')}"
        text = (
            "⚠️ ATENCIÓN ⚠️\n"
            f"El suscriptor {name} ha sido expulsado del Canal VIP. "
            "¿Quieres inhabilitarlo aquí?"
        )
        msg = await self._bot.send_message(
            chat_id=self._owner_id,
            text=text,
            reply_markup=link_kick_keyboard(payload.event_id),
        )
        return int(msg.message_id)

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        _ = chat_id
        await self._bot.send_message(chat_id=self._owner_id, text=text)


__all__ = ["AiogramOwnerNotifier"]
