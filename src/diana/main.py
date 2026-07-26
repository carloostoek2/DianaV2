"""Diana F2 entrypoint — long-polling + safe startup recovery + F2 background jobs."""

from __future__ import annotations

import asyncio
import logging
import sys

from diana.composition import (
    AppContainer,
    build_app,
    load_forbidden_keywords,
    load_runtime_thresholds,
    run_app_startup_recovery,
)
from diana.config import Settings
from diana.jobs.calibration import CalibrationJob
from diana.jobs.gray_zone_expiration import GrayZoneExpirationJob
from diana.jobs.metrics import MetricsJob
from diana.jobs.recontact import RecontactJob
from diana.jobs.trace_purge import TracePurgeJob
from diana.telegram.health import HealthServer

logger = logging.getLogger("diana.composition")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


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

    # F2 Item 4: start gray zone expiration background job.
    expiration_job = _setup_expiration_job(app)
    purge_job = _setup_purge_job(app)
    recontact_job = _setup_recontact_job(app)
    # F3 Pool 3: observational metrics always; calibration only if flag on.
    metrics_job = _setup_metrics_job(app)
    calibration_job = _setup_calibration_job(app)

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
                allowed_updates=["message", "business_message", "callback_query"],
            )
        finally:
            await health.stop()
    finally:
        # Stop new jobs first, then existing F2/F3 jobs.
        await _cancel_job(calibration_job, "calibration_job")
        await _cancel_job(metrics_job, "metrics_job")
        await _cancel_job(recontact_job, "recontact_job")
        await _cancel_job(purge_job, "purge_job")
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


def _setup_recontact_job(app: AppContainer) -> asyncio.Task | None:
    """Start the recontact background job when feature flag is on."""
    if not app.settings.feature_recontact_enabled or app.recontact is None:
        logger.info("recontact_job_skipped_flag_off")
        return None

    job = RecontactJob(app.recontact, interval_seconds=3600)
    task = asyncio.create_task(job.start())
    logger.info("recontact_job_started", extra={"interval_seconds": 3600})
    return task


def _setup_metrics_job(app: AppContainer) -> asyncio.Task | None:
    """Start weekly metrics aggregation when the service is wired."""
    if app.metrics is None:
        logger.info("metrics_job_skipped_no_service")
        return None

    from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore

    config = SqlSystemConfigStore(app.session_factory)
    job = MetricsJob(app.metrics, interval_seconds=3600, config=config)
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


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
