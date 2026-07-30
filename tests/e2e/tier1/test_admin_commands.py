"""E2E: Admin commands -- VIP lifecycle management."""

import pytest
from diana.application.memory import InMemoryVipStore
from diana.cognitive.models import Decision, TurnStatus
from tests.e2e.conftest import make_eval
from tests.e2e.tier1.conftest import build_e2e


@pytest.mark.asyncio
async def test_add_vip_creates_record():
    """Adding a VIP creates a record with telegram_user_id."""
    vips = InMemoryVipStore()
    g = build_e2e([], vip_store=vips)

    record = await g["vips"].add(111, display_name="Test VIP")
    assert record.telegram_user_id == 111
    assert record.display_name == "Test VIP"
    assert record.is_active


@pytest.mark.asyncio
async def test_deactivate_vip_marks_inactive():
    """Deactivating a VIP sets is_active=False."""
    vips = InMemoryVipStore()
    g = build_e2e([], vip_store=vips)

    record = await g["vips"].add(222, display_name="To Remove")
    assert record.is_active

    ok = await g["vips"].deactivate(222)
    assert ok

    stored = await g["vips"].get_by_telegram_user_id(222)
    assert not stored.is_active


@pytest.mark.asyncio
async def test_add_reactivates_deactivated_vip():
    """Adding an already-deactivated VIP reactivates it."""
    vips = InMemoryVipStore()
    g = build_e2e([], vip_store=vips)

    r1 = await g["vips"].add(333, display_name="Vip")
    await g["vips"].deactivate(333)

    r2 = await g["vips"].add(333, display_name="Vip Reactivated")
    assert r2.is_active
    assert r2.display_name == "Vip Reactivated"


@pytest.mark.asyncio
async def test_list_active_excludes_inactive():
    """List active returns only active VIPs."""
    vips = InMemoryVipStore()
    g = build_e2e([], vip_store=vips)

    await g["vips"].add(444, display_name="Active")
    await g["vips"].add(555, display_name="Inactive")
    await g["vips"].deactivate(555)

    active = await g["vips"].list_active()
    assert len(active) == 1
    assert active[0].telegram_user_id == 444


@pytest.mark.asyncio
async def test_freeze_vip_sets_frozen_until():
    """Freezing a VIP sets frozen_until in the future."""
    from datetime import UTC, datetime, timedelta

    vips = InMemoryVipStore()
    g = build_e2e([], vip_store=vips)

    record = await g["vips"].add(666)
    until = datetime.now(UTC) + timedelta(hours=1)
    await g["vips"].freeze_vip(record.id, until)

    stored = await g["vips"].get_by_telegram_user_id(666)
    assert stored.frozen_until is not None


@pytest.mark.asyncio
async def test_rename_vip_updates_display_name():
    """Renaming a VIP updates its display_name."""
    vips = InMemoryVipStore()
    g = build_e2e([], vip_store=vips)

    await g["vips"].add(777, display_name="Old Name")
    updated = await g["vips"].rename(777, "New Name")

    assert updated is not None
    assert updated.display_name == "New Name"


@pytest.mark.asyncio
async def test_pause_vip_sets_paused_until():
    """Pausing a VIP sets paused_until."""
    from datetime import UTC, datetime, timedelta

    vips = InMemoryVipStore()
    g = build_e2e([], vip_store=vips)

    record = await g["vips"].add(888)
    until = datetime.now(UTC) + timedelta(minutes=30)
    await g["vips"].pause_vip(record.id, until)

    stored = await g["vips"].get_by_telegram_user_id(888)
    assert stored.paused_until is not None


@pytest.mark.asyncio
async def test_turnos_returns_turns_for_chat():
    """Coordinator can list non-terminal turns for a chat."""
    from diana.application.ports import VipInboundMessage

    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    await g["orch"].handle_vip_message(msg)

    turns = await g["turns"].list_non_terminal(100)
    assert len(turns) == 1


@pytest.mark.asyncio
async def test_traza_trace_reader_returns_steps():
    """Trace reader returns stored delivery results."""
    from uuid import uuid4

    g = build_e2e([])
    trace_id = uuid4()
    result_dict = {
        "success": True,
        "message_ids": [],
        "texts": ["hello"],
        "actual_delay_seconds": 0.0,
        "typing_duration_seconds": 0.0,
        "error": None,
        "cancelled": False,
    }
    await g["traces"].set_delivery_result(trace_id, result_dict)

    stored = g["traces"].get_delivery_result(trace_id)
    assert stored is not None
    assert stored["success"]
