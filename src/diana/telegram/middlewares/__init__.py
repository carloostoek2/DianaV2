"""F2 middleware stack modules — ErrorHandler outermost (F3 hardener)."""

from __future__ import annotations

from diana.telegram.middlewares.auth import AuthMiddleware
from diana.telegram.middlewares.business_connection import BusinessConnectionMiddleware
from diana.telegram.middlewares.error_handler import ErrorHandlerMiddleware
from diana.telegram.middlewares.forbidden import ForbiddenKeywordsMiddleware
from diana.telegram.middlewares.logging import LoggingMiddleware
from diana.telegram.middlewares.owner import OwnerDetectionMiddleware

# ErrorHandlerMiddleware is F3-hardener outermost (index 0).
F2_MIDDLEWARE_ORDER: tuple[str, ...] = (
    "ErrorHandlerMiddleware",
    "LoggingMiddleware",
    "BusinessConnectionMiddleware",
    "OwnerDetectionMiddleware",
    "FreezeCheckMiddleware",
    "ForbiddenKeywordsMiddleware",
    "AuthMiddleware",
)

__all__ = [
    "AuthMiddleware",
    "BusinessConnectionMiddleware",
    "ErrorHandlerMiddleware",
    "F2_MIDDLEWARE_ORDER",
    "ForbiddenKeywordsMiddleware",
    "LoggingMiddleware",
    "OwnerDetectionMiddleware",
]
