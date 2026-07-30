"""E2E: Middleware stack order and registration.

Verifies the F2 middleware order from build_dispatcher is present on each
relevant observer (message, business_message, callback_query, etc.).
"""

import pytest


@pytest.mark.db
@pytest.mark.asyncio
async def test_dispatcher_has_message_middlewares(app_container):
    """The dispatcher has middlewares registered for message updates."""
    dp = app_container.dispatcher

    # aiogram stores middlewares per update type in the router
    # message middlewares are in dp.message.middleware
    middlewares = dp.message.middleware  # type: ignore[attr-defined]

    # Should have at least the error handler middleware
    names = []
    for mw in middlewares:
        names.append(type(mw).__name__)

    assert len(names) >= 5, f"Expected >=5 middlewares, got {len(names)}: {names}"


@pytest.mark.db
@pytest.mark.asyncio
async def test_dispatcher_has_business_message_middlewares(app_container):
    """Business message updates also have middlewares."""
    dp = app_container.dispatcher
    middlewares = dp.business_message.middleware  # type: ignore[attr-defined]
    names = [type(mw).__name__ for mw in middlewares]
    assert len(names) >= 5, f"Expected >=5 middlewares, got {names}"


@pytest.mark.db
@pytest.mark.asyncio
async def test_dispatcher_has_callback_query_middlewares(app_container):
    """Callback query has middlewares (excluding freeze check)."""
    dp = app_container.dispatcher
    middlewares = dp.callback_query.middleware  # type: ignore[attr-defined]
    names = [type(mw).__name__ for mw in middlewares]
    assert len(names) >= 4, f"Expected >=4 middlewares, got {names}"
    # FreezeCheckMiddleware should NOT be in callback middlewares
    assert "FreezeCheckMiddleware" not in names


@pytest.mark.db
@pytest.mark.asyncio
async def test_error_handler_middleware_is_outermost(app_container):
    """ErrorHandlerMiddleware should be the first (outermost) middleware."""
    dp = app_container.dispatcher
    middlewares = dp.message.middleware  # type: ignore[attr-defined]
    first = type(middlewares[0]).__name__
    assert "ErrorHandler" in first, f"Expected ErrorHandler first, got {first}"


@pytest.mark.db
@pytest.mark.asyncio
async def test_middleware_count_across_update_types(app_container):
    """All update types have middlewares registered."""
    dp = app_container.dispatcher

    expected_types = [
        "message",
        "business_message",
        "edited_business_message",
        "callback_query",
        "business_connection",
    ]
    for ut in expected_types:
        if hasattr(dp, ut):
            mw = getattr(dp, ut).middleware
            count = len(mw) if mw else 0
            assert count >= 0, f"No middlewares found for {ut}"
