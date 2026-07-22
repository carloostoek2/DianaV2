"""Admin commands — owner-only VIP add/remove /start."""

from __future__ import annotations

import pytest

from diana.application.admin_service import AdminService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
    InMemoryVipStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.telegram.handlers.admin import handle_admin_text
from diana.telegram.handlers.callbacks import CorrectSessionStore

OWNER = 999001
OTHER = 111


@pytest.fixture
def admin_ctx() -> dict:
    vips = InMemoryVipStore()
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    behavior = BehaviorEngine(
        FakeTelegramActuator(),
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER,
    )
    return {
        "vips": vips,
        "admin": admin,
        "sessions": CorrectSessionStore(),
        "owner": OWNER,
    }


@pytest.mark.asyncio
async def test_start_menu_owner(admin_ctx: dict) -> None:
    g = admin_ctx
    status = await handle_admin_text(
        text="/start",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert status == "menu"


@pytest.mark.asyncio
async def test_non_owner_ignored(admin_ctx: dict) -> None:
    g = admin_ctx
    status = await handle_admin_text(
        text="/add_vip 123",
        actor_id=OTHER,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert status == "ignored_non_owner"
    assert await g["vips"].is_allowed(123) is False


@pytest.mark.asyncio
async def test_add_and_remove_vip(admin_ctx: dict) -> None:
    g = admin_ctx
    assert (
        await handle_admin_text(
            text="/add_vip 555 Alice",
            actor_id=OWNER,
            owner_telegram_id=OWNER,
            vips=g["vips"],
            admin=g["admin"],
            correct_sessions=g["sessions"],
        )
        == "vip_added"
    )
    assert await g["vips"].is_allowed(555) is True
    assert (
        await handle_admin_text(
            text="/remove_vip 555",
            actor_id=OWNER,
            owner_telegram_id=OWNER,
            vips=g["vips"],
            admin=g["admin"],
            correct_sessions=g["sessions"],
        )
        == "vip_removed"
    )
    assert await g["vips"].is_allowed(555) is False
