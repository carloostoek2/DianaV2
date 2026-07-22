"""Startup recovery orchestration — never auto-send / never auto-approve."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from diana.application.ports import (
    ApprovalRecord,
    DraftNotification,
    OwnerNotifierPort,
    PendingApprovalStore,
    PendingDeliveryStore,
)
from diana.application.recovery import (
    RecoveryPlan,
    classify_pending_deliveries,
    list_waiting_approvals,
)

logger = logging.getLogger("diana.application")

DEFAULT_STALE_AFTER = timedelta(minutes=30)


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class RecoveryStartupReport(BaseModel):
    """Outcome of safe F1 startup recovery."""

    model_config = ConfigDict(extra="forbid")

    expired_delivering_or_stale: int = 0
    expired_recoverable: int = 0
    re_notified_approvals: int = 0
    plan: RecoveryPlan | None = None


async def run_startup_recovery(
    *,
    deliveries: PendingDeliveryStore,
    approvals: PendingApprovalStore,
    notifier: OwnerNotifierPort,
    clock: ClockPort,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> RecoveryStartupReport:
    """Safe F1 recovery on process start.

    - Expire mid-flight ``delivering`` and stale ``pending`` via classify
    - Expire remaining recoverable pending (no silent VIP re-send)
    - Re-notify waiting approvals only (no auto-approve, no cognitive pipeline)
    """
    now = clock.now()
    plan = await classify_pending_deliveries(
        deliveries, now=now, stale_after=stale_after
    )

    expired_recoverable = 0
    for row in plan.recoverable:
        applied = await deliveries.update_status(row.id, "expired")
        if applied:
            expired_recoverable += 1
            await notifier.notify_info(
                f"Startup: expired pending delivery {row.id} for chat "
                f"{row.chat_id}; re-approve required",
                chat_id=row.chat_id,
            )

    waiting = await list_waiting_approvals(approvals)
    re_notified = 0
    for approval in waiting:
        await _renotify_approval(notifier, approval)
        re_notified += 1

    report = RecoveryStartupReport(
        expired_delivering_or_stale=len(plan.to_expire),
        expired_recoverable=expired_recoverable,
        re_notified_approvals=re_notified,
        plan=plan,
    )
    logger.info(
        "startup_recovery",
        extra={
            "expired_midflight": report.expired_delivering_or_stale,
            "expired_recoverable": report.expired_recoverable,
            "re_notified": report.re_notified_approvals,
        },
    )
    return report


async def _renotify_approval(
    notifier: OwnerNotifierPort, approval: ApprovalRecord
) -> None:
    await notifier.notify_draft(
        DraftNotification(
            turn_id=approval.turn_id,
            chat_id=approval.chat_id,
            vip_text="(re-notify on startup)",
            draft_text=approval.draft_text,
            reason="startup_re_notify",
            evaluation_summary=approval.cognitive_summary,
            evaluation=approval.evaluation,
            business_connection_id=approval.business_connection_id,
            reply_markup_spec={
                "actions": ["approve", "correct", "escalate"],
                "turn_id": str(approval.turn_id),
            },
        )
    )


__all__ = [
    "DEFAULT_STALE_AFTER",
    "RecoveryStartupReport",
    "run_startup_recovery",
]
