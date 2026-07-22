"""Diana F1 entrypoint — long-polling + safe startup recovery."""

from __future__ import annotations

import asyncio
import logging
import sys

from diana.composition import (
    build_app,
    load_forbidden_keywords,
    run_app_startup_recovery,
)
from diana.config import Settings

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
    await app.dispatcher.start_polling(
        app.bot,
        allowed_updates=["message", "business_message", "callback_query"],
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
