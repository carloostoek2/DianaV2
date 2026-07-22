"""F1 middleware stack modules."""

from __future__ import annotations

from diana.telegram.middlewares.auth import AuthMiddleware
from diana.telegram.middlewares.business_connection import BusinessConnectionMiddleware
from diana.telegram.middlewares.forbidden import ForbiddenKeywordsMiddleware
from diana.telegram.middlewares.logging import LoggingMiddleware
from diana.telegram.middlewares.owner import OwnerDetectionMiddleware

# F1 order — FreezeCheck intentionally absent.
F1_MIDDLEWARE_ORDER: tuple[str, ...] = (
    "LoggingMiddleware",
    "BusinessConnectionMiddleware",
    "OwnerDetectionMiddleware",
    "ForbiddenKeywordsMiddleware",
    "AuthMiddleware",
)

__all__ = [
    "AuthMiddleware",
    "BusinessConnectionMiddleware",
    "F1_MIDDLEWARE_ORDER",
    "ForbiddenKeywordsMiddleware",
    "LoggingMiddleware",
    "OwnerDetectionMiddleware",
]
