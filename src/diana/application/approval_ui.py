"""Best-effort owner DM cleanup when approvals are cancelled by supersede."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from diana.application.draft_variants import build_owner_draft_text, resolve_vip_display_name
from diana.application.ports import ApprovalRecord, OwnerNotifierPort, VipStore

logger = logging.getLogger("diana.application")

_REASON_LEGENDS = {
    "owner_message": "Cancelado porque la dueña escribió en el chat",
    "new_message": "Cancelado por reenvío de mensaje del usuario",
}


class ApprovalDraftVoider:
    """Strip draft keyboards and mark messages as cancelled, keeping the draft."""

    def __init__(
        self, notifier: OwnerNotifierPort, vips: VipStore | None = None
    ) -> None:
        self._notifier = notifier
        self._vips = vips

    async def on_approvals_cancelled(
        self,
        records: Sequence[ApprovalRecord],
        *,
        reason: str,
    ) -> None:
        void = getattr(self._notifier, "void_draft", None)
        for rec in records:
            mid = rec.owner_message_id
            if mid is None:
                continue
            if not callable(void):
                logger.info(
                    "approval_void_skipped_no_void_draft",
                    extra={
                        "turn_id": str(rec.turn_id),
                        "owner_message_id": mid,
                    },
                )
                continue
            legend = _REASON_LEGENDS.get(reason, "Cancelado")
            # Keep the draft body for audit; prepend the cancel legend like the
            # approved path prepends "Enviado".
            vip_name = await resolve_vip_display_name(
                self._vips, rec.vip_id, rec.chat_id
            )
            text = (
                f"⚠️ <b>{legend}</b>\n"
                "No se envió al VIP. Los botones quedaron desactivados.\n\n"
                f"{build_owner_draft_text(rec, vip_name=vip_name)}"
            )
            try:
                await void(owner_message_id=int(mid), text=text)
            except Exception:
                logger.exception(
                    "approval_void_draft_failed",
                    extra={
                        "turn_id": str(rec.turn_id),
                        "owner_message_id": mid,
                        "reason": reason,
                    },
                )


__all__ = ["ApprovalDraftVoider"]
