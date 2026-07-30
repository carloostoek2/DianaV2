"""E2E: VIP message -> autonomous send -> auto-delivery."""

import pytest
from diana.application.ports import VipInboundMessage
from diana.cognitive.models import Decision, TurnStatus
from tests.e2e.conftest import make_eval
from tests.e2e.tier1.conftest import build_e2e


@pytest.mark.asyncio
async def test_autonomous_send_delivers_without_owner_approval():
    """Autonomous mode: send decision delivers immediately, no approval needed."""
    decision = Decision(action="send", reason="autonomous ok", evaluation=make_eval(), draft_text="auto reply")
    g = build_e2e([decision], wire_autonomous=True, global_mode="autonomous", feature_autonomous_mode=True)

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.DELIVERED
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "auto reply"


@pytest.mark.asyncio
async def test_autonomous_send_no_approval_record():
    """Autonomous send does NOT create a pending approval record."""
    decision = Decision(action="send", reason="ok", evaluation=make_eval(), draft_text="auto")
    g = build_e2e([decision], wire_autonomous=True, global_mode="autonomous", feature_autonomous_mode=True)

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is None


@pytest.mark.asyncio
async def test_send_with_ams_disabled_demotes_to_approve():
    """Send decision with feature flag off falls back to approve (pending_approval)."""
    decision = Decision(action="send", reason="ok", evaluation=make_eval(), draft_text="auto")
    g = build_e2e([decision], wire_autonomous=True, global_mode="supervised", feature_autonomous_mode=False)

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.PENDING_APPROVAL
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_send_without_behavior_wiring_marks_failed():
    """Autonomous send without behavior wired marks turn failed."""
    decision = Decision(action="send", reason="ok", evaluation=make_eval(), draft_text="auto")
    g = build_e2e([decision], wire_autonomous=True, global_mode="autonomous", feature_autonomous_mode=True)
    g["orch"]._behavior = None  # Simulate missing behavior

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.FAILED


@pytest.mark.asyncio
async def test_send_appends_owner_history():
    """Autonomous delivery appends owner message to history."""
    decision = Decision(action="send", reason="ok", evaluation=make_eval(), draft_text="auto reply")
    g = build_e2e([decision], wire_autonomous=True, global_mode="autonomous", feature_autonomous_mode=True)

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.DELIVERED
