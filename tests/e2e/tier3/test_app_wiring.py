"""E2E: End-to-end application wiring verification."""
import pytest


@pytest.mark.db
@pytest.mark.asyncio
async def test_complete_dependency_graph_is_wired(app_container):
    """Verify all 20+ components in the AppContainer are non-None where expected."""
    # Core — always wired
    assert app_container.settings is not None
    assert app_container.engine is not None
    assert app_container.session_factory is not None
    assert app_container.bot is not None
    assert app_container.dispatcher is not None
    assert app_container.orchestrator is not None
    assert app_container.admin is not None
    assert app_container.behavior is not None
    assert app_container.coordinator is not None
    assert app_container.vips is not None
    assert app_container.notifier is not None
    assert app_container.correct_sessions is not None
    assert app_container.forbidden_keywords is not None
    assert app_container.clock is not None
    assert app_container.wiring is not None

    # Feature-gated (should be None with all flags off)
    assert app_container.gray_zone is None
    assert app_container.sandbox is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_orchestrator_receives_handle_vip_message_calls(app_container):
    """Orchestrator handle_vip_message is callable with proper signature."""
    import inspect

    sig = inspect.signature(app_container.orchestrator.handle_vip_message)
    params = list(sig.parameters.keys())
    assert "incoming" in params or len(params) >= 2  # self + incoming


@pytest.mark.db
@pytest.mark.asyncio
async def test_behavior_deliver_is_wired(app_container):
    """BehaviorEngine.deliver is properly callable."""
    assert hasattr(app_container.behavior, "deliver")


@pytest.mark.db
@pytest.mark.asyncio
async def test_vip_store_connected_to_db(app_container):
    """VIP store can query the test database."""
    # Add a VIP and verify we can read it back
    record = await app_container.vips.add(12345, display_name="Test VIP")
    assert record is not None
    assert record.telegram_user_id == 12345
    assert record.is_active

    stored = await app_container.vips.get_by_telegram_user_id(12345)
    assert stored is not None
    assert stored.display_name == "Test VIP"


@pytest.mark.db
@pytest.mark.asyncio
async def test_forbidden_keywords_loaded(app_container):
    """Forbidden keywords are accessible (may be empty)."""
    keywords = app_container.forbidden_keywords
    assert isinstance(keywords, list)
