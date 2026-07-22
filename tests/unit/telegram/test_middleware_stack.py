"""F1 middleware registration order — Freeze absent."""

from __future__ import annotations

from diana.telegram.middlewares import F1_MIDDLEWARE_ORDER
from diana.telegram.setup import registered_middleware_names


def test_f1_middleware_order() -> None:
    assert registered_middleware_names() == (
        "LoggingMiddleware",
        "BusinessConnectionMiddleware",
        "OwnerDetectionMiddleware",
        "ForbiddenKeywordsMiddleware",
        "AuthMiddleware",
    )
    assert F1_MIDDLEWARE_ORDER == registered_middleware_names()


def test_freeze_check_absent() -> None:
    names = registered_middleware_names()
    assert not any("Freeze" in n for n in names)
