"""F2 middleware stack modules — ErrorHandler outermost (F3 hardener)."""

from __future__ import annotations

from diana.telegram.middlewares.auth import AuthMiddleware
from diana.telegram.middlewares.business_connection import BusinessConnectionMiddleware
from diana.telegram.middlewares.dedup import DedupMiddleware
from diana.telegram.middlewares.error_handler import ErrorHandlerMiddleware
from diana.telegram.middlewares.forbidden import ForbiddenKeywordsMiddleware
from diana.telegram.middlewares.link import LinkCoordinatorMiddleware
from diana.telegram.middlewares.logging import LoggingMiddleware
from diana.telegram.middlewares.owner import OwnerDetectionMiddleware
from diana.telegram.middlewares.rate_limit import RateLimitMiddleware

# ErrorHandlerMiddleware is F3-hardener outermost (index 0).
# Order: ErrorHandler → Dedup → RateLimit → Logging → BC → Link → Owner → Freeze → Auth → Forbidden
# Auth before Forbidden so non-VIP business never J.4-escalates / owner-notify spam.
F2_MIDDLEWARE_ORDER: tuple[str, ...] = (
    "ErrorHandlerMiddleware",
    "DedupMiddleware",
    "RateLimitMiddleware",
    "LoggingMiddleware",
    "BusinessConnectionMiddleware",
    "LinkCoordinatorMiddleware",
    "OwnerDetectionMiddleware",
    "FreezeCheckMiddleware",
    "AuthMiddleware",
    "ForbiddenKeywordsMiddleware",
)

__all__ = [
    "AuthMiddleware",
    "BusinessConnectionMiddleware",
    "DedupMiddleware",
    "ErrorHandlerMiddleware",
    "F2_MIDDLEWARE_ORDER",
    "ForbiddenKeywordsMiddleware",
    "LinkCoordinatorMiddleware",
    "LoggingMiddleware",
    "OwnerDetectionMiddleware",
    "RateLimitMiddleware",
]
