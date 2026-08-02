"""Best-effort owner DM cleanup when approvals are cancelled by supersede."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from diana.application.ports import ApprovalRecord, OwnerNotifierPort

logger = logging.getLogger("diana.application")

_REASON_LABELS = {
    "owner_message": "la dueña escribió en el chat",
    "new_message": "el VIP envió otro mensaje",
}


class ApprovalDraftVoider:
    """Strip draft keyboards and mark messages as no longer applicable."""

    def __init__(self, notifier: OwnerNotifierPort) -> None:
        self._notifier = notifier

    async def on_approvals_cancelled(
        self,
        records: Sequence[ApprovalRecord],
        *,
        reason: str,
    ) -> None:
        label = _REASON_LABELS.get(reason, reason)
        text = (
            f"⚠️ Este borrador ya no aplica ({label}).\n"
            "No se envió al VIP. Los botones quedaron desactivados."
        )
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
