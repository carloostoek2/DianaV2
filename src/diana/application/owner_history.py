"""Shared owner outbound history pairing after successful delivery.

Application-owned: BehaviorEngine never writes history; it only returns
``DeliveryResult.message_ids`` + ``texts`` for 1:1 pairing.
"""

from __future__ import annotations

import logging
from uuid import UUID

from diana.application.ports import DeliveryResult, MessageHistoryWriter

logger = logging.getLogger("diana.application")


def build_owner_history_pairs(
    result: DeliveryResult,
    fallback_text: str,
) -> list[tuple[str, int | None]]:
    """Map a successful delivery result to (segment_text, telegram_message_id) pairs.

    Locked pairing rules (CLARIFY / PLAN):
    - empty message_ids → one pair (fallback, None)
    - len(texts) == len(ids) → zip 1:1
    - mismatch → first id gets fallback (or segs[0]); remaining use segs[i]
      or "" (id linkage only — never duplicate full fallback on every id)
    """
    ids = list(result.message_ids or [])
    segs = list(result.texts or [])

    if not ids:
        return [(fallback_text, None)]

    if len(segs) == len(ids):
        return list(zip(segs, ids, strict=True))

    pairs: list[tuple[str, int | None]] = []
    for i, mid in enumerate(ids):
        if i == 0:
            pairs.append((fallback_text if not segs else segs[0], mid))
        elif i < len(segs):
            pairs.append((segs[i], mid))
        else:
            pairs.append(("", mid))
    return pairs


async def append_owner_delivery_history(
    history: MessageHistoryWriter,
    chat_id: int,
    *,
    result: DeliveryResult,
    fallback_text: str,
    turn_id: UUID | None = None,
) -> None:
    """Append one owner history row per pair. Per-row try/except; never re-raises.

    Caller must gate sandbox ``should_persist`` once before calling.
    """
    pairs = build_owner_history_pairs(result, fallback_text)
    for seg_text, mid in pairs:
        try:
            await history.append(
                chat_id,
                role="owner",
                text=seg_text,
                telegram_message_id=mid,
            )
        except Exception:
            logger.exception(
                "owner_history_append_failed",
                extra={
                    "turn_id": str(turn_id) if turn_id is not None else None,
                    "chat_id": chat_id,
                    "telegram_message_id": mid,
                },
            )
