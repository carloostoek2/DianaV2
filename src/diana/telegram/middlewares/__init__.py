"""F2 middleware stack modules — ErrorHandler outermost (F3 hardener)."""

from __future__ import annotations

from diana.telegram.middlewares.auth import AuthMiddleware
from diana.telegram.middlewares.business_connection import BusinessConnectionMiddleware
from diana.telegram.middlewares.dedup import DedupMiddleware
from diana.telegram.middlewares.error_handler import ErrorHandlerMiddleware
from diana.telegram.middlewares.forbidden import ForbiddenKeywordsMiddleware
from diana.telegram.middlewares.horario import HorarioAtencionMiddleware
from diana.telegram.middlewares.link import LinkCoordinatorMiddleware
from diana.telegram.middlewares.logging import LoggingMiddleware
from diana.telegram.middlewares.owner import OwnerDetectionMiddleware
from diana.telegram.middlewares.rate_limit import RateLimitMiddleware

# ErrorHandlerMiddleware is F3-hardener outermost (index 0).
# Order: ErrorHandler → Dedup → RateLimit → Logging → BC → Link → Owner → Freeze →
#        Auth → Horario → Forbidden
# Auth before Forbidden so non-VIP business never J.4-escalates / owner-notify spam.
# Horario between Auth and Forbidden: Auth supplies vip_id/channel_type, and the
# hours gate must run BEFORE the deterministic escalation, which sends a reply.
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
    "HorarioAtencionMiddleware",
    "ForbiddenKeywordsMiddleware",
)

__all__ = [
    "AuthMiddleware",
    "BusinessConnectionMiddleware",
    "DedupMiddleware",
    "ErrorHandlerMiddleware",
    "F2_MIDDLEWARE_ORDER",
    "ForbiddenKeywordsMiddleware",
    "HorarioAtencionMiddleware",
    "LinkCoordinatorMiddleware",
    "LoggingMiddleware",
    "OwnerDetectionMiddleware",
    "RateLimitMiddleware",
]
