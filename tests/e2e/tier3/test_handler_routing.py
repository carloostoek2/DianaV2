"""E2E: Handler routing — correct handlers for each update type.

Validates that the sub-router tree contains the expected named routers and
each has at least one handler registered for its update type.
"""

import pytest

from aiogram import Dispatcher


def _find_router_by_name(dp: Dispatcher, name: str):
    """Search the sub-router tree (one level deep) for a router by name."""
    for router in dp.sub_routers:
        if router.name == name:
            return router
        for sub in router.sub_routers:
            if sub.name == name:
                return sub
    return None


@pytest.mark.db
@pytest.mark.asyncio
async def test_business_message_handler_registered(app_container):
    """Business message router has at least one handler."""
    dp = app_container.dispatcher
    business_router = _find_router_by_name(dp, "business")
    assert business_router is not None, "business router not found in sub-routers"
    handlers = business_router.business_message.handlers  # type: ignore[attr-defined]
    assert len(handlers) >= 1, (
        f"Expected >=1 business message handler, got {len(handlers)}"
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_admin_commands_registered(app_container):
    """Admin router has command handlers registered."""
    dp = app_container.dispatcher
    admin_router = _find_router_by_name(dp, "admin")
    assert admin_router is not None, "admin router not found in sub-routers"
    handlers = admin_router.message.handlers  # type: ignore[attr-defined]
    assert len(handlers) >= 1, f"Expected >=1 message handler, got {len(handlers)}"


@pytest.mark.db
@pytest.mark.asyncio
async def test_callback_query_handler_registered(app_container):
    """Callback query has at least one handler."""
    dp = app_container.dispatcher
    callback_router = _find_router_by_name(dp, "callbacks")
    assert callback_router is not None, "callbacks router not found in sub-routers"
    handlers = callback_router.callback_query.handlers  # type: ignore[attr-defined]
    assert len(handlers) >= 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_business_connection_handler_registered(app_container):
    """Business connection has a handler for lifecycle events."""
    dp = app_container.dispatcher
    bc_router = _find_router_by_name(dp, "business_connection")
    assert bc_router is not None, (
        "business_connection router not found in sub-routers"
    )
    handlers = bc_router.business_connection.handlers  # type: ignore[attr-defined]
    assert len(handlers) >= 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_app_container_has_all_key_services(app_container):
    """The wired AppContainer has all expected services."""
    fields = [
        "dispatcher",
        "orchestrator",
        "admin",
        "behavior",
        "coordinator",
        "bot",
        "settings",
        "vips",
    ]
    for field in fields:
        assert hasattr(app_container, field), f"Missing field: {field}"
        assert getattr(app_container, field) is not None, f"Field is None: {field}"
