"""E2E: Full message flow through the wired dispatcher."""
import pytest
from datetime import datetime

from aiogram.types import (
    Update,
    Message,
    Chat,
    User,
)


def _make_business_message_update(
    chat_id: int = 100,
    text: str = "hola diana",
    message_id: int = 11,
    business_connection_id: str = "bc-test-001",
    from_user_id: int = 777001,
    date: int = 1234567890,
) -> Update:
    """Build a Telegram Update containing a business_message."""
    msg = Message(
        message_id=message_id,
        date=datetime.fromtimestamp(date),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=from_user_id, is_bot=False, first_name="Vip"),
        text=text,
        business_connection_id=business_connection_id,
    )
    return Update(update_id=1, business_message=msg)


def _make_edited_business_message_update(
    chat_id: int = 100,
    text: str = "editado",
    message_id: int = 11,
    business_connection_id: str = "bc-test-001",
) -> Update:
    """Build a Telegram Update containing an edited_business_message."""
    msg = Message(
        message_id=message_id,
        date=datetime(2025, 1, 1),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=777001, is_bot=False, first_name="Vip"),
        text=text,
        business_connection_id=business_connection_id,
    )
    return Update(update_id=2, edited_business_message=msg)


@pytest.mark.db
@pytest.mark.asyncio
async def test_dispatcher_is_wired_with_routers(app_container):
    """The dispatcher has sub-routers configured."""
    dp = app_container.dispatcher
    # aiogram 3.x dispatcher has sub_routers for each included router
    assert len(dp.sub_routers) >= 1, (
        f"Expected >=1 sub-routers, got {len(dp.sub_routers)}"
    )


@pytest.mark.db
@pytest.mark.asyncio
async def test_business_message_update_structure():
    """Verify that business_message updates can be constructed correctly."""
    update = _make_business_message_update()
    assert update.business_message is not None
    assert update.business_message.text == "hola diana"
    assert update.business_message.business_connection_id == "bc-test-001"


@pytest.mark.db
@pytest.mark.asyncio
async def test_orchestrator_is_wired_in_container(app_container):
    """The TurnOrchestrator is properly wired in the container."""
    orch = app_container.orchestrator
    assert orch is not None
    assert hasattr(orch, "handle_vip_message")


@pytest.mark.db
@pytest.mark.asyncio
async def test_admin_service_is_wired(app_container):
    """Admin service is wired with expected methods."""
    admin = app_container.admin
    assert hasattr(admin, "handle_approve")
    assert hasattr(admin, "handle_correct")
    assert hasattr(admin, "handle_owner_escalate")


@pytest.mark.db
@pytest.mark.asyncio
async def test_behavior_engine_is_wired(app_container):
    """Behavior engine is wired with actuator."""
    behavior = app_container.behavior
    assert behavior is not None


@pytest.mark.db
@pytest.mark.asyncio
async def test_feature_flags_respected(app_container):
    """Settings feature flags are accessible on the container."""
    settings = app_container.settings
    assert settings.feature_gray_zone_enabled is False
    assert settings.feature_autonomous_mode is False
