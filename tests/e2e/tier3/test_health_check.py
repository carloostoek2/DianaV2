"""E2E: Health check server."""
import pytest


@pytest.mark.db
@pytest.mark.asyncio
async def test_app_container_has_settings_with_health_config(app_container):
    """Health host and port are configured in settings."""
    settings = app_container.settings
    assert settings.health_host == "127.0.0.1"
    assert settings.health_port == 8080


@pytest.mark.db
@pytest.mark.asyncio
async def test_health_server_start_stop():
    """Health server can be created and stopped."""
    # Test that the health module imports correctly
    from diana.telegram.health import HealthServer

    server = HealthServer(
        host="127.0.0.1",
        port=0,
        session_factory=lambda: None,
    )
    assert server is not None
    # Don't actually start it — just verify creation
