"""Startup recovery orchestration — never auto-send / never auto-approve."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from diana.application.ports import (
    ApprovalRecord,
    DeliveryContext,
    DeliveryRecord,
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
    recovered_deliveries: int = 0
    plan: RecoveryPlan | None = None


async def run_startup_recovery(
    *,
    deliveries: PendingDeliveryStore,
    approvals: PendingApprovalStore,
    notifier: OwnerNotifierPort,
    clock: ClockPort,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    behavior: object | None = None,
    vips: object | None = None,
    global_mode: str = "supervised",
) -> RecoveryStartupReport:
    """Safe F1 recovery on process start.

    - Expire mid-flight ``delivering`` and stale ``pending`` via classify
    - Recover fresh ``pending`` deliveries via BehaviorEngine (when available)
    - Re-notify waiting approvals only (no auto-approve, no cognitive pipeline)
    - Send recovery summary DM to owner
    """
    now = clock.now()
    plan = await classify_pending_deliveries(
        deliveries, now=now, stale_after=stale_after
    )

    recovered = 0
    if behavior is not None and vips is not None:
        recovered = await _recover_deliveries(
            plan.recoverable,
            behavior=behavior,
            vips=vips,
            global_mode=global_mode,
        )
    else:
        # Fallback: expire recoverable (pre-recovery behavior, also used in tests)
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
        expired_recoverable=0 if behavior is not None else len(plan.recoverable),
        re_notified_approvals=re_notified,
        recovered_deliveries=recovered,
        plan=plan,
    )
    logger.info(
        "startup_recovery",
        extra={
            "expired_midflight": report.expired_delivering_or_stale,
            "expired_recoverable": report.expired_recoverable,
            "re_notified": report.re_notified_approvals,
            "recovered": report.recovered_deliveries,
        },
    )

    if recovered or re_notified or plan.to_expire:
        await _notify_recovery_summary(notifier, report)

    return report


async def _recover_deliveries(
    recoverable: list[DeliveryRecord],
    *,
    behavior: object,
    vips: object,
    global_mode: str,
) -> int:
    """Re-schedule fresh pending deliveries that survived a restart.

    Each delivery is spawned as a background task so the recovery function
    returns promptly. The BehaviorEngine handles all safety gates (freeze,
    supersede, pre-send liveness).
    """
    if not recoverable:
        return 0

    spawned = 0
    for record in recoverable:
        is_frozen = False
        if record.vip_id is not None:
            try:
                vip = await vips.get_by_id(record.vip_id)  # type: ignore[union-attr]
                if vip is not None and vip.frozen_until is not None:
                    frozen = vip.frozen_until
                    if frozen.tzinfo is None:
                        from datetime import UTC
                        frozen = frozen.replace(tzinfo=UTC)
                    is_frozen = frozen > datetime.now(UTC)
            except Exception:
                logger.exception(
                    "recovery_vip_lookup_failed",
                    extra={"vip_id": str(record.vip_id)},
                )

        ctx = DeliveryContext(
            chat_id=record.chat_id,
            business_connection_id=record.business_connection_id,
            vip_id=record.vip_id,
            mode=global_mode,  # type: ignore[arg-type]
            is_frozen=is_frozen,
            skip_initial_delay=False,
            allow_split=False,
            allow_human_quirks=False,
        )

        _ = asyncio.create_task(
            behavior.recover_pending_delivery(record, ctx)  # type: ignore[union-attr]
        )
        spawned += 1

    if spawned:
        logger.info(
            "recovery_deliveries_spawned",
            extra={"count": spawned},
        )
    return spawned


async def _notify_recovery_summary(
    notifier: OwnerNotifierPort, report: RecoveryStartupReport
) -> None:
    """Send a concise recovery summary DM to the owner."""
    lines = ["Recuperacion tras reinicio:"]
    if report.recovered_deliveries:
        lines.append(
            f"  • {report.recovered_deliveries} entrega(s) reanudada(s)"
        )
    if report.re_notified_approvals:
        lines.append(
            f"  • {report.re_notified_approvals} borrador(es) re-notificado(s)"
        )
    if report.expired_delivering_or_stale:
        lines.append(
            f"  • {report.expired_delivering_or_stale} entrega(s) expirada(s)"
            " (en vuelo o caducada)"
        )
    if not any(
        [report.recovered_deliveries, report.re_notified_approvals,
         report.expired_delivering_or_stale]
    ):
        lines.append("  Nada que recuperar.")
    lines.append("")
    lines.append("Revisa borradores anteriores si los botones no responden.")
    await notifier.notify_info("\n".join(lines))


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
