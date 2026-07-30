"""Crash-recovery cognitive helpers — zombie turns + draft re-materialization.

Never calls the LLM pipeline. Reads from traces only.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from diana.application.ports import (
    ApprovalRecord,
    DraftNotification,
    OwnerNotifierPort,
    PendingApprovalStore,
    TurnRecord,
    TurnStore,
)
from diana.application.recovery import list_zombie_turns

_logger = logging.getLogger("diana.application")


async def recover_zombie_turns(turns: TurnStore) -> int:
    """Mark all non-terminal turns as FAILED with error='crash_recovery'.

    Returns count of successfully marked turns.
    Each transition is wrapped in try/except to handle
    terminal-latch races and DB connectivity errors.
    """
    zombies = await list_zombie_turns(turns)
    count = 0
    for turn in zombies:
        try:
            await turns.transition(turn.id, "failed", error="crash_recovery")
            count += 1
        except Exception:
            # Turn was terminal-latched between list and transition; skip.
            pass
    _logger.info(
        "recover_zombie_turns",
        extra={"zombie_count": len(zombies), "marked": count},
    )
    return count


async def rematerialize_drafts(
    rematerializable: list[tuple[TurnRecord, str]],
    approvals: PendingApprovalStore,
    notifier: OwnerNotifierPort,
) -> int:
    """Create PendingApproval rows + re-notify for each rematerializable draft.

    ``rematerializable`` is a list of (turn, generated_text) tuples from
    ``list_rematerializable_turns``.

    ``business_connection_id`` is set to ``""`` for re-materialized drafts.
    The actual BC is set by ``Admin.send_approve`` when the draft is approved.
    The BC is not available on ``TurnRecord`` at recovery time.

    Returns count of successfully rematerialized drafts.
    """
    count = 0
    for turn, generated_text in rematerializable:
        try:
            draft_id = uuid4()
            _logger.info(
                "rematerialize_draft",
                extra={
                    "turn_id": str(turn.id),
                    "chat_id": turn.chat_id,
                    "draft_id": str(draft_id),
                },
            )

            # Create approval record FIRST — if this fails, no notification sent.
            # If notification fails, the approval exists and will be re-notified
            # on next startup.
            await approvals.create_waiting(
                ApprovalRecord(
                    id=draft_id,
                    turn_id=turn.id,
                    chat_id=turn.chat_id,
                    business_connection_id="",
                    draft_text=generated_text,
                    status="waiting",
                )
            )

            await notifier.notify_draft(
                DraftNotification(
                    turn_id=turn.id,
                    chat_id=turn.chat_id,
                    vip_text="(crash recovery)",
                    draft_text=generated_text,
                    reason="crash_rematerialized",
                    evaluation_summary=None,
                    evaluation=None,
                    business_connection_id="",
                    reply_markup_spec={
                        "actions": ["approve", "correct", "escalate"],
                        "turn_id": str(turn.id),
                    },
                )
            )
            count += 1
        except Exception:
            _logger.exception(
                "rematerialize_draft_failed",
                extra={"turn_id": str(turn.id)},
            )
    _logger.info(
        "rematerialize_drafts_done",
        extra={"count": count, "total": len(rematerializable)},
    )
    return count
