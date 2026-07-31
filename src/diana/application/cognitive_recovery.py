"""Crash-recovery cognitive helpers — zombie turns + draft re-materialization.

Never calls the LLM pipeline. Reads from traces only.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from diana.application.ports import (
    ApprovalRecord,
    OwnerNotifierPort,
    PendingApprovalStore,
    TurnRecord,
    TurnStore,
)
from diana.application.recovery import list_zombie_turns

_logger = logging.getLogger("diana.application")


async def recover_zombie_turns(turns: TurnStore) -> int:
    """Mark mid-pipeline crash zombies as FAILED with error='crash_recovery'.

    Does **not** fail ``pending_approval`` / ``gray_zone`` (owner still deciding).
    Returns count of successfully marked turns.
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
    turns: TurnStore | None = None,
) -> int:
    """Create waiting approvals and park turns as ``pending_approval``.

    Call **before** zombie recovery so turns are still non-terminal and can
    transition to ``pending_approval``. Notification is left to the startup
    re-notify pass (avoids double DMs).

    ``business_connection_id`` may be empty when unknown at recovery time;
    owner re-notify still works; deliver needs a real BC when present on the
    waiting approval row from a normal supervised path.

    Returns count of successfully rematerialized drafts.
    """
    count = 0
    for turn, generated_text in rematerializable:
        try:
            existing = await approvals.get_by_turn(turn.id)
            if existing is not None and existing.status == "waiting":
                # Already have a waiting draft — just ensure turn status.
                if turns is not None:
                    await turns.transition(turn.id, "pending_approval")
                count += 1
                continue

            draft_id = uuid4()
            _logger.info(
                "rematerialize_draft",
                extra={
                    "turn_id": str(turn.id),
                    "chat_id": turn.chat_id,
                    "draft_id": str(draft_id),
                },
            )

            await approvals.create_waiting(
                ApprovalRecord(
                    id=draft_id,
                    turn_id=turn.id,
                    chat_id=turn.chat_id,
                    business_connection_id="",
                    draft_text=generated_text,
                    status="waiting",
                    vip_id=turn.vip_id,
                    trigger_message_id=turn.trigger_message_id,
                )
            )

            # Keep Approve path non-terminal: owner is still deciding.
            if turns is not None:
                await turns.transition(turn.id, "pending_approval")

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
