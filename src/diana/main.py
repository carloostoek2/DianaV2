"""Diana F2 entrypoint — long-polling + safe startup recovery + F2 background jobs."""

from __future__ import annotations

import asyncio
import logging
import sys

from diana.application.logformat import ColorExtraFormatter
from diana.application.missed_message_recovery import recover_missed_updates
from diana.composition import (
    AppContainer,
    build_app,
    load_forbidden_keywords,
    load_runtime_thresholds,
    run_app_pre_delay_recovery,
    run_app_startup_recovery,
)
from diana.config import Settings
from diana.jobs.agent_data_purge import AgentDataPurgeJob
from diana.jobs.backfill import BackfillJob
from diana.jobs.calibration import CalibrationJob
from diana.jobs.gray_zone_expiration import GrayZoneExpirationJob
from diana.jobs.metrics import MetricsJob
from diana.jobs.outcome_reaction import OutcomeReactionJob
from diana.jobs.profile_synthesis_job import ProfileSynthesisJob
from diana.jobs.recontact import RecontactJob
from diana.jobs.trace_purge import TracePurgeJob
from diana.telegram.health import HealthServer

logger = logging.getLogger("diana.composition")


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorExtraFormatter())
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]
    # PTB v21+ polling uses httpx — without this every getUpdates floods the console.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _cancel_job(task: asyncio.Task | None, name: str) -> None:
    """Cancel a background job task and wait briefly for clean stop."""
    if task is None:
        return
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=10.0)
    except TimeoutError:
        logger.warning("%s_stop_timeout", name)
    except (asyncio.CancelledError, Exception):
        pass


async def async_main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    app = build_app(settings)
    await load_forbidden_keywords(app)
    await load_runtime_thresholds(app)
    report = await run_app_startup_recovery(app)
    logger.info(
        "startup_complete",
        extra={
            "expired_midflight": report.expired_delivering_or_stale,
            "expired_recoverable": report.expired_recoverable,
            "re_notified": report.re_notified_approvals,
        },
    )

    # F4: recover any business messages that arrived while the bot was offline.
    # Fetches+ACKs getUpdates, then runs handlers in background so VIP pre_delay
    # (e.g. 120s supervised) does not block health/jobs/polling startup.
    # Must run BEFORE VIP pre_delay resume so offline owner/VIP traffic can
    # supersede waiting_delay turns (handlers race via TurnCoordinator).
    try:
        missed = await recover_missed_updates(bot=app.bot, dispatcher=app.dispatcher)
        if missed.total_updates:
            logger.info(
                "missed_updates_recovered",
                extra={
                    "business": missed.recovered_business_messages,
                    "regular": missed.recovered_regular_messages,
                    "total": missed.total_updates,
                    "handlers_scheduled": missed.handlers_scheduled,
                },
            )
    except BaseException:
        logger.exception("missed_message_recovery_failed")

    # D1: schedule resume of VIP human waits that survived the restart.
    # Sleeps run in background tasks (same non-blocking posture as missed feeds).
    try:
        pre_n = await run_app_pre_delay_recovery(app)
        if pre_n:
            logger.info("pre_delay_recovered", extra={"count": pre_n})
    except BaseException:
        logger.exception("pre_delay_recovery_failed")

    # F2 Item 4: start gray zone expiration background job.
    expiration_job = _setup_expiration_job(app)
    purge_job = _setup_purge_job(app)
    agent_purge_job = _setup_agent_data_purge_job(app)
    recontact_job = _setup_recontact_job(app)
    # F3 Pool 3: observational metrics always; calibration only if flag on.
    metrics_job = _setup_metrics_job(app)
    calibration_job = _setup_calibration_job(app)
    # Fila 4 (C3): close VIP reaction windows (classify / silence) — only when
    # the quality measurement flag is on.
    outcome_reaction_job = _setup_outcome_reaction_job(app)
    # Evo-Agente Fase 1: profile-synthesis cycle (scan + drain + synthesize).
    profile_synthesis_job = _setup_profile_synthesis_job(app)
    # F5 Pool 2: backfill scheduler (flag-gated; recover_stale inside start()).
    backfill_job = _setup_backfill_job(app)

    # F5 Pool 2: enqueue missing VIP profiles at startup (before polling,
    # NEVER during turn processing). Best-effort.
    if app.backfill_queue is not None:
        try:
            await app.backfill_queue.enqueue_missing_vips()
        except Exception:
            logger.exception("backfill_missing_enqueue_failed")

    health = HealthServer(
        host=settings.health_host,
        port=settings.health_port,
        session_factory=app.session_factory,
        bot=app.bot,
    )
    # Outer finally always cancels jobs even if health bind or polling fails.
    try:
        # Soft-fail health bind: bot polling continues if port is busy (G2-OPS-1).
        try:
            await health.start()
        except OSError:
            logger.exception(
                "health_start_failed",
                extra={
                    "host": settings.health_host,
                    "port": settings.health_port,
                },
            )
        try:
            await app.dispatcher.start_polling(
                app.bot,
                allowed_updates=["business_connection", "message", "business_message", "edited_business_message", "callback_query"],
            )
        finally:
            await health.stop()
    finally:
        # Stop new jobs first, then existing F2/F3 jobs.
        await _cancel_job(backfill_job, "backfill_job")
        await _cancel_job(profile_synthesis_job, "profile_synthesis_job")
        await _cancel_job(calibration_job, "calibration_job")
        await _cancel_job(outcome_reaction_job, "outcome_reaction_job")
        await _cancel_job(metrics_job, "metrics_job")
        await _cancel_job(recontact_job, "recontact_job")
        await _cancel_job(purge_job, "purge_job")
        await _cancel_job(agent_purge_job, "agent_purge_job")
        await _cancel_job(expiration_job, "expiration_job")


def _setup_expiration_job(app: AppContainer) -> asyncio.Task | None:
    """Start the gray zone expiration background job if gray_zone is enabled."""
    if app.gray_zone is None:
        logger.info("expiration_job_skipped_gray_zone_disabled")
        return None

    job = GrayZoneExpirationJob(
        app.gray_zone,
        coordinator=app.coordinator,
        notifier=app.notifier,
        admin=app.admin,
        interval_seconds=300,
    )
    task = asyncio.create_task(job.start())
    logger.info("expiration_job_started", extra={"interval_seconds": 300})
    return task


def _setup_purge_job(app: AppContainer) -> asyncio.Task | None:
    """Start the trace TTL purge background job."""
    if app.trace_store is None:
        logger.info("purge_job_skipped_no_trace_store")
        return None

    job = TracePurgeJob(app.trace_store, interval_seconds=3600)
    task = asyncio.create_task(job.start())
    logger.info("purge_job_started", extra={"interval_seconds": 3600})
    return task


def _setup_agent_data_purge_job(app: AppContainer) -> asyncio.Task | None:
    """Start the agent-evolution TTL purge job (TTL per table from settings)."""
    stores = [
        (app.vip_profile_history_repo, app.settings.vip_profile_history_ttl_days),
        (app.turn_category_log_repo, app.settings.turn_category_log_ttl_days),
        (app.emotional_signal_log_repo, app.settings.emotional_signal_log_ttl_days),
        # REQ-MEM-06: interpreted context snapshots are expiry-gated rows
        # (expires_at); the store's purge hook deletes only truly expired ones.
        (app.contexts_repo, 1),
    ]
    stores = [(s, ttl) for s, ttl in stores if s is not None]
    if not stores:
        logger.info("agent_data_purge_job_skipped_no_stores")
        return None

    job = AgentDataPurgeJob(stores, interval_seconds=3600)
    task = asyncio.create_task(job.start())
    logger.info("agent_data_purge_job_started", extra={"stores": len(stores)})
    return task


def _setup_recontact_job(app: AppContainer) -> asyncio.Task | None:
    """Start the recontact background job when feature flag is on."""
    if not app.settings.feature_recontact_enabled or app.recontact is None:
        logger.info("recontact_job_skipped_flag_off")
        return None

    job = RecontactJob(app.recontact, interval_seconds=3600)
    task = asyncio.create_task(job.start())
    logger.info("recontact_job_started", extra={"interval_seconds": 3600})
    return task


def _setup_backfill_job(app: AppContainer) -> asyncio.Task | None:
    """Start the VIP profile backfill scheduler when the memory flag is on.

    ``BackfillJob.start()`` recovers stale ``processing`` jobs at boot and
    then processes one unit (one transcript window) per cycle, sleeping
    ``backfill_interval_sec`` between units. Flag OFF → job never starts.
    """
    if not app.settings.feature_memory_enabled or app.backfill_queue is None:
        logger.info("backfill_job_skipped_flag_off")
        return None

    job = BackfillJob(
        app.backfill_queue,
        interval_seconds=app.settings.backfill_interval_sec,
        wake=app.backfill_wake,
        recover_stale_max_age_sec=app.settings.backfill_recover_stale_max_age_sec,
    )
    task = asyncio.create_task(job.start())
    logger.info(
        "backfill_job_started",
        extra={"interval_seconds": app.settings.backfill_interval_sec},
    )
    return task


def _setup_metrics_job(app: AppContainer) -> asyncio.Task | None:
    """Start weekly metrics aggregation when the service is wired."""
    if app.metrics is None:
        logger.info("metrics_job_skipped_no_service")
        return None

    from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore

    config = SqlSystemConfigStore(app.session_factory)
    job = MetricsJob(
        app.metrics,
        interval_seconds=3600,
        config=config,
        atencion_counts=app.metrics_data,
        feature_general_mode_enabled=app.settings.feature_general_mode_enabled,
    )
    task = asyncio.create_task(job.start())
    logger.info("metrics_job_started", extra={"interval_seconds": 3600})
    return task


def _setup_calibration_job(app: AppContainer) -> asyncio.Task | None:
    """Start calibration job only when FEATURE_CALIBRATION_ENABLED is on."""
    if not app.settings.feature_calibration_enabled or app.calibration is None:
        logger.info("calibration_job_skipped_flag_off")
        return None

    job = CalibrationJob(app.calibration, interval_seconds=3600)
    task = asyncio.create_task(job.start())
    logger.info("calibration_job_started", extra={"interval_seconds": 3600})
    return task


def _setup_outcome_reaction_job(app: AppContainer) -> asyncio.Task | None:
    """Start the C3 reaction backstop only when the Fila 4 quality flag is on."""
    if (
        not app.settings.feature_autonomy_quality_enabled
        or app.outcome_log is None
        or app.history is None
    ):
        logger.info("outcome_reaction_job_skipped_flag_off")
        return None

    job = OutcomeReactionJob(
        app.outcome_log,
        app.history,
        window_hours=app.settings.outcome_reaction_window_hours,
        interval_seconds=3600,
    )
    task = asyncio.create_task(job.start())
    logger.info(
        "outcome_reaction_job_started",
        extra={
            "window_hours": app.settings.outcome_reaction_window_hours,
            "interval_seconds": 3600,
        },
    )
    return task


def _setup_profile_synthesis_job(app: AppContainer) -> asyncio.Task | None:
    """Start the Fase 1 profile-synthesis job only when the flag is on.

    The job wraps the trigger (scan_inactivity) + synthesis service
    (drain + synthesize); it is created only when both are wired (A8). Flag OFF
    → skip without starting any task.
    """
    if (
        not app.settings.feature_profile_synthesis_enabled
        or app.profile_synthesis_service is None
    ):
        logger.info("profile_synthesis_job_skipped_flag_off")
        return None

    job = ProfileSynthesisJob(
        app.profile_synthesis_trigger,
        app.profile_synthesis_service,
        interval_seconds=app.settings.profile_synthesis_scan_interval_seconds,
    )
    task = asyncio.create_task(job.start())
    logger.info(
        "profile_synthesis_job_started",
        extra={
            "interval_seconds": app.settings.profile_synthesis_scan_interval_seconds
        },
    )
    return task


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
