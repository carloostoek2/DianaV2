"""Diana F2 entrypoint — long-polling + safe startup recovery + F2 background jobs."""

from __future__ import annotations

import asyncio
import logging
import sys

from diana.composition import (
    AppContainer,
    build_app,
    load_forbidden_keywords,
    run_app_startup_recovery,
)
from diana.config import Settings
from diana.jobs.gray_zone_expiration import GrayZoneExpirationJob

logger = logging.getLogger("diana.composition")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


async def async_main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    app = build_app(settings)
    await load_forbidden_keywords(app)
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

    try:
        await app.dispatcher.start_polling(
            app.bot,
            allowed_updates=["message", "business_message", "callback_query"],
        )
    finally:
        if expiration_job is not None:
            expiration_job.cancel()
            try:
                await asyncio.wait_for(expiration_job, timeout=10.0)
            except TimeoutError:
                logger.warning("expiration_job_stop_timeout")
            except (asyncio.CancelledError, Exception):
                pass


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


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
