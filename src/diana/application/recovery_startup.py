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
    DeliveryResult,
    DraftNotification,
    OwnerNotifierPort,
    PendingApprovalStore,
    PendingDeliveryStore,
    RuntimeTimerRecord,
    RuntimeTimerStore,
    TraceReader,
    TurnRecord,
    TurnStore,
)
from diana.application.promo_service import PROMO_DECISION_KIND
from diana.application.cognitive_recovery import (
    recover_zombie_turns,
    rematerialize_drafts,
)
from diana.application.recovery import (
    RecoveryPlan,
    classify_pending_deliveries,
    list_rematerializable_turns,
    list_waiting_approvals,
)
from diana.cognitive.models import is_turn_status_terminal

logger = logging.getLogger("diana.application")

DEFAULT_STALE_AFTER = timedelta(minutes=30)


class ClockPort(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


async def _clock_sleep(clock: ClockPort, seconds: float) -> None:
    """Prefer clock.sleep (testable ImmediateClock); fall back to asyncio."""
    sleep = getattr(clock, "sleep", None)
    if callable(sleep):
        await sleep(seconds)
        return
    if seconds > 0:
        await asyncio.sleep(seconds)


class RecoveryStartupReport(BaseModel):
    """Outcome of safe F1 startup recovery."""

    model_config = ConfigDict(extra="forbid")

    expired_delivering_or_stale: int = 0
    expired_recoverable: int = 0
    re_notified_approvals: int = 0
    orphan_approvals_cancelled: int = 0
    recovered_deliveries: int = 0
    zombie_turns_expired: int = 0
    drafts_rematerialized: int = 0
    timers_recovered: int = 0
    promos_recovered: int = 0
    plan: RecoveryPlan | None = None


class PromoFinalizePort(Protocol):
    """Bookkeeping after a promo delivery is resumed post-restart."""

    async def finalize_recovered_delivery(
        self,
        *,
        chat_id: int,
        turn_id: object,
        texts: list[str],
        decision: dict | None,
        result: DeliveryResult,
    ) -> None: ...


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
    promo: PromoFinalizePort | None = None,
) -> RecoveryStartupReport:
    """Safe F1 recovery on process start.

    - Expire mid-flight ``delivering`` and stale ``pending`` via classify
    - Recover fresh ``pending`` deliveries via BehaviorEngine (when available)
    - Mark zombie turns as FAILED with ``crash_recovery`` when TurnStore available
    - Re-materialize drafts from pipeline_traces for turns with generated_text
    - Recover active runtime timers with adjusted remaining delays
    - Resume non-VIP promo mid-wait (decision.kind=promo) without auto-approve
    - Re-notify waiting approvals only (no auto-approve, no cognitive pipeline)
    - Send recovery summary DM to owner
    """
    now = clock.now()

    # Timer recovery: re-schedule deliveries whose in-flight delay was interrupted.
    timer_recovered = 0
    promos_recovered = 0
    if timers is not None and behavior is not None:
        timer_recovered, promos_recovered = await _recover_timers(
            timers,
            deliveries,
            behavior,
            global_mode,
            clock,
            promo=promo,
        )

    plan = await classify_pending_deliveries(
        deliveries, now=now, stale_after=stale_after
    )

    # Draft re-materialization BEFORE zombie kill:
    # 1) mid-pipeline turns with generated_text → waiting approval + pending_approval
    # 2) then fail only true pipeline zombies (not pending_approval / gray_zone)
    remat_count = 0
    if turns is not None and traces is not None:
        rematerializable = await list_rematerializable_turns(turns, traces)
        if rematerializable:
            remat_count = await rematerialize_drafts(
                rematerializable, approvals, notifier, turns=turns
            )

    # Zombie recovery: mid-pipeline only (owner-waiting turns stay alive).
    zombie_count = 0
    if turns is not None:
        zombie_count = await recover_zombie_turns(turns)

    recovered = 0
    promos_from_deliveries = 0
    if behavior is not None and vips is not None:
        recovered, promos_from_deliveries = await _recover_deliveries(
            plan.recoverable,
            behavior=behavior,
            vips=vips,
            global_mode=global_mode,
            promo=promo,
        )
        promos_recovered += promos_from_deliveries
    else:
        # Fallback: expire recoverable (pre-recovery behavior, also used in tests)
        # Except promo rows: keep them only when promo finalize port is wired.
        expired_recoverable = 0
        for row in plan.recoverable:
            if _is_promo_delivery(row) and promo is not None:
                continue
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
    orphan_cancelled = 0
    for approval in waiting:
        # Defense in depth: never re-notify an approval whose turn is terminal
        # (failed/superseded) or gone — its buttons would be dead. Cancel the
        # orphan so it stops being re-notified on every startup (BUG: stale
        # drafts from crash recovery used to loop forever).
        if turns is not None:
            live = await turns.get(approval.turn_id)
            if live is None or is_turn_status_terminal(live.status):
                try:
                    await approvals.mark_status(approval.turn_id, "cancelled")
                except Exception:
                    logger.exception(
                        "recovery_orphan_cancel_failed",
                        extra={"turn_id": str(approval.turn_id)},
                    )
                else:
                    orphan_cancelled += 1
                    logger.info(
                        "approval_orphan_cancelled",
                        extra={
                            "turn_id": str(approval.turn_id),
                            "turn_status": None if live is None else live.status,
                        },
                    )
                continue
        mid = await _renotify_approval(notifier, approval)
        if mid is not None:
            try:
                await approvals.set_owner_message_id(approval.turn_id, mid)
            except Exception:
                logger.exception(
                    "recovery_set_owner_message_id_failed",
                    extra={"turn_id": str(approval.turn_id)},
                )
        re_notified += 1

    report = RecoveryStartupReport(
        expired_delivering_or_stale=len(plan.to_expire),
        expired_recoverable=0 if behavior is not None else len(plan.recoverable),
        re_notified_approvals=re_notified,
        orphan_approvals_cancelled=orphan_cancelled,
        recovered_deliveries=recovered,
        zombie_turns_expired=zombie_count,
        drafts_rematerialized=remat_count,
        timers_recovered=timer_recovered,
        promos_recovered=promos_recovered,
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
            "promos_recovered": report.promos_recovered,
        },
    )

    if (
        recovered
        or re_notified
        or orphan_cancelled
        or plan.to_expire
        or zombie_count
        or remat_count
        or timer_recovered
        or promos_recovered
    ):
        await _notify_recovery_summary(notifier, report)

    return report


def _is_promo_delivery(record: DeliveryRecord) -> bool:
    dec = record.decision
    return isinstance(dec, dict) and dec.get("kind") == PROMO_DECISION_KIND


async def _recover_deliveries(
    recoverable: list[DeliveryRecord],
    *,
    behavior: object,
    vips: object,
    global_mode: str,
    promo: PromoFinalizePort | None = None,
) -> tuple[int, int]:
    """Re-schedule fresh pending deliveries that survived a restart.

    Returns (spawned_or_completed_count, promo_count).

    VIP rows are background tasks. Promo rows are awaited so bookkeeping
    (promo_executions + turn status) is correct before startup finishes.
    """
    if not recoverable:
        return 0, 0

    spawned = 0
    promos = 0
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

        is_promo = _is_promo_delivery(record)
        ctx = DeliveryContext(
            chat_id=record.chat_id,
            business_connection_id=record.business_connection_id,
            vip_id=record.vip_id,
            mode=global_mode,  # type: ignore[arg-type]
            is_frozen=is_frozen,
            # Promo already waited (or will wait via timer path); skip full delay.
            skip_initial_delay=is_promo,
            allow_split=False,
            allow_human_quirks=False,
            parse_mode="HTML" if is_promo else None,
        )

        if is_promo:
            try:
                result = await behavior.recover_pending_delivery(  # type: ignore[union-attr]
                    record, ctx
                )
                if promo is not None:
                    await promo.finalize_recovered_delivery(
                        chat_id=record.chat_id,
                        turn_id=record.turn_id,
                        texts=list(record.texts),
                        decision=record.decision
                        if isinstance(record.decision, dict)
                        else None,
                        result=result,
                    )
                promos += 1
                spawned += 1
            except Exception:
                logger.exception(
                    "promo_delivery_recovery_failed",
                    extra={
                        "delivery_id": str(record.id),
                        "chat_id": record.chat_id,
                    },
                )
            continue

        _ = asyncio.create_task(
            behavior.recover_pending_delivery(record, ctx)  # type: ignore[union-attr]
        )
        spawned += 1

    if spawned:
        logger.info(
            "recovery_deliveries_spawned",
            extra={"count": spawned, "promos": promos},
        )
    return spawned, promos


async def _recover_one_timer(
    timer: RuntimeTimerRecord,
    timers: RuntimeTimerStore,
    deliveries: PendingDeliveryStore,
    behavior: object,
    global_mode: str,
    clock: ClockPort,
    promo: PromoFinalizePort | None = None,
) -> tuple[int, int]:
    """Recover a single active **delivery** timer.

    Returns (timer_recovered: 0|1, promo_recovered: 0|1).
    ``kind=pre_delay`` is handled by ``resume_pre_delay_timers`` after missed updates.
    """
    kind = (timer.kind or "delivery").strip() or "delivery"
    if kind == "pre_delay":
        return 0, 0

    now_val = clock.now()
    elapsed = (now_val - timer.scheduled_at).total_seconds()
    remaining = timer.initial_delay_seconds - elapsed

    try:
        if timer.delivery_id is None:
            await timers.mark_completed(timer.id)
            return 0, 0
        delivery = await deliveries.get(timer.delivery_id)
        if delivery is None or delivery.status not in ("pending", "delivering"):
            await timers.mark_completed(timer.id)
            return 0, 0

        is_promo = _is_promo_delivery(delivery)

        # VIP grace: drop late timers. Promo: still send (product: do not lose promo).
        if remaining <= 5.0 and not is_promo:
            try:
                await timers.mark_completed(timer.id)
            except Exception:
                pass
            return 0, 0

        if remaining > 0:
            await _clock_sleep(clock, remaining)

        ctx = DeliveryContext(
            chat_id=delivery.chat_id,
            business_connection_id=delivery.business_connection_id,
            vip_id=delivery.vip_id,
            mode=global_mode,  # type: ignore[arg-type]
            skip_initial_delay=True,
            allow_split=False,
            allow_human_quirks=False,
            parse_mode="HTML" if is_promo else None,
        )

        if is_promo:
            # Await full sequence + bookkeeping so zombies never race the turn.
            result = await behavior.deliver(  # type: ignore[union-attr]
                texts=list(delivery.texts),
                ctx=ctx,
                turn_id=delivery.turn_id,
                decision=delivery.decision,
            )
            if promo is not None:
                await promo.finalize_recovered_delivery(
                    chat_id=delivery.chat_id,
                    turn_id=delivery.turn_id,
                    texts=list(delivery.texts),
                    decision=delivery.decision
                    if isinstance(delivery.decision, dict)
                    else None,
                    result=result,
                )
            await deliveries.update_status(delivery.id, "expired")
            await timers.mark_completed(timer.id)
            return 1, 1

        _ = asyncio.create_task(
            behavior.deliver(  # type: ignore[union-attr]
                texts=list(delivery.texts),
                ctx=ctx,
                turn_id=delivery.turn_id,
                decision=delivery.decision,
            )
        )
        await deliveries.update_status(delivery.id, "expired")
        await timers.mark_completed(timer.id)
        return 1, 0
    except Exception:
        logger.exception(
            "timer_recovery_failed",
            extra={"timer_id": str(timer.id)},
        )
        return 0, 0


async def _recover_timers(
    timers: RuntimeTimerStore,
    deliveries: PendingDeliveryStore,
    behavior: object,
    global_mode: str,
    clock: ClockPort,
    promo: PromoFinalizePort | None = None,
) -> tuple[int, int]:
    """Recover active runtime timers.

    Returns (timers_recovered, promos_recovered).
    """
    active = await timers.list_active()
    if not active:
        return 0, 0

    results = await asyncio.gather(*[
        _recover_one_timer(
            t, timers, deliveries, behavior, global_mode, clock, promo=promo
        )
        for t in active
    ])
    recovered = sum(r for r, _ in results)
    promos = sum(p for _, p in results)
    if recovered:
        logger.info(
            "timers_recovered",
            extra={
                "count": recovered,
                "promos": promos,
                "total": len(active),
            },
        )
    return recovered, promos


async def _notify_recovery_summary(
    notifier: OwnerNotifierPort, report: RecoveryStartupReport
) -> None:
    """Send a concise recovery summary DM to the owner."""
    lines = ["Recuperacion tras reinicio:"]
    if report.recovered_deliveries:
        lines.append(
            f"  • {report.recovered_deliveries} entrega(s) reanudada(s)"
        )
    if report.promos_recovered:
        lines.append(
            f"  • {report.promos_recovered} promo(s) no-VIP reanudada(s)"
        )
    if report.re_notified_approvals:
        lines.append(
            f"  • {report.re_notified_approvals} borrador(es) re-notificado(s)"
        )
    if report.orphan_approvals_cancelled:
        lines.append(
            f"  • {report.orphan_approvals_cancelled} borrador(es) sin turno"
            " activo descartado(s)"
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
            report.orphan_approvals_cancelled,
            report.expired_delivering_or_stale,
            report.zombie_turns_expired,
            report.drafts_rematerialized,
            report.timers_recovered,
        ]
    ):
        lines.append("  Nada que recuperar.")
    lines.append("")
    lines.append(
        "Los borradores re-notificados se pueden aprobar desde el mensaje nuevo."
    )
    await notifier.notify_info("\n".join(lines))


async def _renotify_approval(
    notifier: OwnerNotifierPort, approval: ApprovalRecord
) -> int | None:
    """Re-send draft keyboard; return new owner message id when available."""
    return await notifier.notify_draft(
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


async def resume_pre_delay_timers(
    *,
    timers: RuntimeTimerStore,
    turns: TurnStore,
    orchestrator: object,
    clock: ClockPort,
) -> int:
    """Resume VIP pre-pipeline waits after missed-update recovery (D1).

    For each active ``kind=pre_delay`` timer whose turn is still
    ``waiting_delay``, sleep remaining time and continue the cognitive path
    via ``orchestrator.resume_waiting_delay``. Orphan ``waiting_delay`` turns
    without a live timer are failed with ``crash_recovery``.
    """
    from uuid import UUID as _UUID

    from diana.application.ports import VipInboundMessage

    active = await timers.list_active()
    pre_delay = [t for t in active if (t.kind or "delivery") == "pre_delay"]
    resumed = 0

    async def _one(timer: RuntimeTimerRecord) -> int:
        live = await turns.get(timer.turn_id)
        if live is None or live.status != "waiting_delay":
            try:
                await timers.mark_completed(timer.id)
            except Exception:
                pass
            return 0
        payload = timer.payload if isinstance(timer.payload, dict) else {}
        raw_in = (
            payload.get("incoming")
            if isinstance(payload.get("incoming"), dict)
            else {}
        )
        try:
            vip_epoch = int(payload.get("vip_epoch") or 0)
        except (TypeError, ValueError):
            vip_epoch = 0
        vip_raw = raw_in.get("vip_id")
        vip_id = None
        if vip_raw:
            try:
                vip_id = _UUID(str(vip_raw))
            except (TypeError, ValueError):
                vip_id = None
        incoming = VipInboundMessage(
            chat_id=int(raw_in.get("chat_id") or timer.chat_id),
            text=str(raw_in.get("text") or ""),
            telegram_message_id=raw_in.get("telegram_message_id"),
            business_connection_id=raw_in.get("business_connection_id"),
            vip_id=vip_id,
            is_edit=bool(raw_in.get("is_edit")),
            channel_type=str(raw_in.get("channel_type") or "vip"),
        )
        now_val = clock.now()
        elapsed = (now_val - timer.scheduled_at).total_seconds()
        remaining = max(0.0, float(timer.initial_delay_seconds) - elapsed)
        try:
            await orchestrator.resume_waiting_delay(  # type: ignore[union-attr]
                turn_id=timer.turn_id,
                incoming=incoming,
                vip_epoch=vip_epoch,
                remaining_seconds=remaining,
            )
            await timers.mark_completed(timer.id)
            return 1
        except Exception:
            logger.exception(
                "pre_delay_resume_failed",
                extra={
                    "timer_id": str(timer.id),
                    "turn_id": str(timer.turn_id),
                },
            )
            try:
                await timers.mark_completed(timer.id)
            except Exception:
                pass
            return 0

    if pre_delay:
        results = await asyncio.gather(*[_one(t) for t in pre_delay])
        resumed = sum(results)

    # Fail orphan waiting_delay (no timer, or resume left them stranded).
    try:
        non_term = await turns.list_all_non_terminal()
    except Exception:
        non_term = []
    orphans = 0
    for rec in non_term:
        if rec.status != "waiting_delay":
            continue
        try:
            await turns.transition(rec.id, "failed", error="crash_recovery")
            orphans += 1
            logger.info(
                "waiting_delay_orphan_failed",
                extra={"turn_id": str(rec.id), "chat_id": rec.chat_id},
            )
        except Exception:
            logger.exception(
                "waiting_delay_orphan_fail_failed",
                extra={"turn_id": str(rec.id)},
            )

    if resumed or orphans:
        logger.info(
            "pre_delay_recovery_done",
            extra={"resumed": resumed, "orphans_failed": orphans},
        )
    return resumed


__all__ = [
    "DEFAULT_STALE_AFTER",
    "RecoveryStartupReport",
    "resume_pre_delay_timers",
    "run_startup_recovery",
]
