"""Pending deliveries / approvals recovery helpers for process restart (item 4).

Classification only — never auto-send or auto-approve.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from diana.application.ports import (
    ApprovalRecord,
    DeliveryRecord,
    PendingApprovalStore,
    PendingDeliveryStore,
    TraceReader,
    TurnRecord,
    TurnStore,
)

logger = logging.getLogger("diana.application")


class RecoveryPlan(BaseModel):
    """Classification of pending_deliveries rows for restart rehydration."""

    model_config = ConfigDict(extra="forbid")

    recoverable: list[DeliveryRecord] = Field(default_factory=list)
    to_expire: list[DeliveryRecord] = Field(default_factory=list)


async def classify_pending_deliveries(
    store: PendingDeliveryStore,
    *,
    now: datetime,
    stale_after: timedelta,
) -> RecoveryPlan:
    """Classify active delivery rows for restart.

    Rules (F1 supervised, safe):
    - ``delivering`` → always expire (crash mid-flight; never re-send without re-approval)
    - ``pending`` older than ``stale_after`` → expire
    - ``pending`` fresh → recoverable DTO for item 4 to reschedule (still no auto-send
      without an owner approval path — item 4 must not invent approve)
    - done / cancelled / expired → ignored
    """
    active = await store.list_active()
    recoverable: list[DeliveryRecord] = []
    to_expire: list[DeliveryRecord] = []
    threshold = now - stale_after

    for row in active:
        scheduled = row.scheduled_at
        if scheduled.tzinfo is None and now.tzinfo is not None:
            scheduled = scheduled.replace(tzinfo=now.tzinfo)

        # Mid-flight delivering is never auto-resumed in F1.
        if row.status == "delivering":
            applied = await store.update_status(row.id, "expired")
            if applied:
                to_expire.append(row.model_copy(update={"status": "expired"}))
            continue

        if scheduled < threshold:
            applied = await store.update_status(row.id, "expired")
            if applied:
                to_expire.append(row.model_copy(update={"status": "expired"}))
        else:
            recoverable.append(row)

    logger.info(
        "classify_pending_deliveries",
        extra={
            "recoverable": len(recoverable),
            "expired": len(to_expire),
        },
    )
    return RecoveryPlan(recoverable=recoverable, to_expire=to_expire)


async def list_waiting_approvals(
    approvals: PendingApprovalStore,
) -> list[ApprovalRecord]:
    """List waiting approvals for item 4 re-notify only (no auto-approve)."""
    return await approvals.list_waiting()


# Mid-pipeline only. Owner-waiting states must survive restart so Approve works.
# pending_approval / gray_zone wait on the owner — never treat as crash zombies.
ZOMBIE_PIPELINE_STATUSES: frozenset[str] = frozenset(
    {
        "received",
        "analyzing",
        "planning",
        "retrieving",
        "building_context",
        "generating",
        "evaluating",
        "deciding",
    }
)


async def list_zombie_turns(turns: TurnStore) -> list[TurnRecord]:
    """Return mid-pipeline turns for FAILED marking after crash.

    Excludes ``pending_approval`` and ``gray_zone`` (owner is still deciding).
    """
    non_terminal = await turns.list_all_non_terminal()
    return [t for t in non_terminal if t.status in ZOMBIE_PIPELINE_STATUSES]


async def list_rematerializable_turns(
    turns: TurnStore,
    traces: TraceReader,
) -> list[tuple[TurnRecord, str]]:
    """Return (turn, generated_text) for turns in {GENERATING, EVALUATING, DECIDING}
    that have generated_text in pipeline_traces.

    Uses string values for status to avoid importing cognitive.models.
    """
    non_terminal = await turns.list_all_non_terminal()
    rematerializable: list[tuple[TurnRecord, str]] = []
    for turn in non_terminal:
        if turn.status not in {"generating", "evaluating", "deciding"}:
            continue
        trace = await traces.get_full_trace(turn.id)
        if trace is None:
            continue
        generated = trace.get("generated_text")
        if generated and isinstance(generated, str) and generated.strip():
            rematerializable.append((turn, generated))
    return rematerializable


__all__ = [
    "RecoveryPlan",
    "ZOMBIE_PIPELINE_STATUSES",
    "classify_pending_deliveries",
    "list_rematerializable_turns",
    "list_waiting_approvals",
    "list_zombie_turns",
]
