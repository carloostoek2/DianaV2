"""F2 middleware stack modules — FreezeCheck added at position 4."""

from __future__ import annotations

from diana.telegram.middlewares.auth import AuthMiddleware
from diana.telegram.middlewares.business_connection import BusinessConnectionMiddleware
from diana.telegram.middlewares.forbidden import ForbiddenKeywordsMiddleware
from diana.telegram.middlewares.logging import LoggingMiddleware
from diana.telegram.middlewares.owner import OwnerDetectionMiddleware

F2_MIDDLEWARE_ORDER: tuple[str, ...] = (
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
    "F2_MIDDLEWARE_ORDER",
    "ForbiddenKeywordsMiddleware",
    "LoggingMiddleware",
    "OwnerDetectionMiddleware",
]
