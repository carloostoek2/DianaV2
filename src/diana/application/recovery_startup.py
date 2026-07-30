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
    RuntimeTimerStore,
    TraceReader,
    TurnStore,
)
from diana.application.recovery import (
    RecoveryPlan,
    classify_pending_deliveries,
    list_rematerializable_turns,
    list_waiting_approvals,
    list_zombie_turns,
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
    zombie_turns_expired: int = 0
    drafts_rematerialized: int = 0
    timers_recovered: int = 0
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
    # NEW (all optional for backwards compat):
    turns: TurnStore | None = None,
    traces: TraceReader | None = None,
    timers: RuntimeTimerStore | None = None,
) -> RecoveryStartupReport:
    """Safe F1 recovery on process start.

    - Expire mid-flight ``delivering`` and stale ``pending`` via classify
    - Recover fresh ``pending`` deliveries via BehaviorEngine (when available)
    - Mark zombie turns as FAILED with ``crash_recovery`` when TurnStore available
    - Re-materialize drafts from pipeline_traces for turns with generated_text
    - Recover active runtime timers with adjusted remaining delays
    - Re-notify waiting approvals only (no auto-approve, no cognitive pipeline)
    - Send recovery summary DM to owner
    """
    now = clock.now()

    # Timer recovery: re-schedule deliveries whose in-flight delay was interrupted.
    timer_recovered = 0
    if timers is not None and behavior is not None:
        timer_recovered = await _recover_timers(
            timers, deliveries, behavior, global_mode, clock
        )

    plan = await classify_pending_deliveries(
        deliveries, now=now, stale_after=stale_after
    )

    # Zombie turn recovery: mark all non-terminal turns as FAILED.
    zombie_count = 0
    if turns is not None:
        from diana.application.cognitive_recovery import recover_zombie_turns

        zombie_count = await recover_zombie_turns(turns)

    # Draft re-materialization: create pending_approval for turns with generated_text.
    remat_count = 0
    if turns is not None and traces is not None:
        from diana.application.cognitive_recovery import rematerialize_drafts

        rematerializable = await list_rematerializable_turns(turns, traces)
        if rematerializable:
            remat_count = await rematerialize_drafts(
                rematerializable, approvals, notifier
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
        zombie_turns_expired=zombie_count,
        drafts_rematerialized=remat_count,
        timers_recovered=timer_recovered,
        plan=plan,
    )
    logger.info(
        "startup_recovery",
        extra={
            "expired_midflight": report.expired_delivering_or_stale,
            "expired_recoverable": report.expired_recoverable,
            "re_notified": report.re_notified_approvals,
            "recovered": report.recovered_deliveries,
            "zombie_turns_expired": report.zombie_turns_expired,
            "drafts_rematerialized": report.drafts_rematerialized,
            "timers_recovered": report.timers_recovered,
        },
    )

    if (
        recovered
        or re_notified
        or plan.to_expire
        or zombie_count
        or remat_count
        or timer_recovered
    ):
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


async def _recover_timers(
    timers: RuntimeTimerStore,
    deliveries: PendingDeliveryStore,
    behavior: object,
    global_mode: str,
    clock: ClockPort,
) -> int:
    """Recover active runtime timers by re-scheduling deliveries with reduced delay.

    For each active timer with meaningful remaining time (>5s grace), marks the
    old delivery as expired and re-creates it via ``behavior.deliver`` with
    ``skip_initial_delay=True`` after sleeping the remaining time.
    Returns count of successfully recovered timers.
    """
    active = await timers.list_active()
    now_val = clock.now()
    recovered = 0
    for timer in active:
        elapsed = (now_val - timer.scheduled_at).total_seconds()
        remaining = timer.initial_delay_seconds - elapsed
        if remaining <= 5.0:
            # Grace period exhausted; mark timer completed without re-scheduling.
            try:
                await timers.mark_completed(timer.id)
            except Exception:
                pass
            continue
        try:
            delivery = await deliveries.get(timer.delivery_id)
            if delivery is None or delivery.status not in ("pending", "delivering"):
                # Delivery already resolved; just mark timer completed.
                await timers.mark_completed(timer.id)
                continue

            # Mark old delivery as expired so recovery doesn't double-process it.
            await deliveries.update_status(delivery.id, "expired")

            # Sleep remaining time, then deliver with skip_initial_delay=True.
            await asyncio.sleep(remaining)
            ctx = DeliveryContext(
                chat_id=delivery.chat_id,
                business_connection_id=delivery.business_connection_id,
                vip_id=delivery.vip_id,
                mode=global_mode,  # type: ignore[arg-type]
                skip_initial_delay=True,
                allow_split=False,
                allow_human_quirks=False,
            )
            _ = asyncio.create_task(
                behavior.deliver(  # type: ignore[union-attr]
                    texts=list(delivery.texts),
                    ctx=ctx,
                    turn_id=delivery.turn_id,
                    decision=delivery.decision,
                )
            )
            await timers.mark_completed(timer.id)
            recovered += 1
        except Exception:
            logger.exception(
                "timer_recovery_failed",
                extra={"timer_id": str(timer.id)},
            )
    if recovered:
        logger.info(
            "timers_recovered",
            extra={"count": recovered, "total": len(active)},
        )
    return recovered


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
    if report.zombie_turns_expired:
        lines.append(
            f"  • {report.zombie_turns_expired} turn(s) zombie marcado(s) como fallido(s)"
        )
    if report.drafts_rematerialized:
        lines.append(
            f"  • {report.drafts_rematerialized} borrador(es) re-materializado(s) desde traces"
        )
    if report.timers_recovered:
        lines.append(
            f"  • {report.timers_recovered} timer(s) de entrega recuperado(s)"
        )
    if not any(
        [
            report.recovered_deliveries,
            report.re_notified_approvals,
            report.expired_delivering_or_stale,
            report.zombie_turns_expired,
            report.drafts_rematerialized,
            report.timers_recovered,
        ]
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
