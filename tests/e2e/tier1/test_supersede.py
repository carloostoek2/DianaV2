"""E2E: Message B supersedes A while pending."""

import pytest
from diana.application.ports import VipInboundMessage
from diana.cognitive.models import Decision, TurnStatus
from tests.e2e.conftest import make_eval
from tests.e2e.tier1.conftest import build_e2e


@pytest.mark.asyncio
async def test_message_b_supersedes_a():
    """When B arrives while A is pending, A is superseded and B becomes active."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="reply A")
    g = build_e2e([decision, decision])  # Two decisions for two messages

    msg_a = VipInboundMessage(chat_id=100, text="primero", telegram_message_id=1, business_connection_id="bc-vip")
    turn_a = await g["orch"].handle_vip_message(msg_a)
    assert (await g["turns"].get(turn_a)).status == TurnStatus.PENDING_APPROVAL

    msg_b = VipInboundMessage(chat_id=100, text="segundo", telegram_message_id=2, business_connection_id="bc-vip")
    turn_b = await g["orch"].handle_vip_message(msg_b)

    # Turn A superseded
    stored_a = await g["turns"].get(turn_a)
    assert stored_a.status == TurnStatus.SUPERSEDED

    # Turn B is the active one
    stored_b = await g["turns"].get(turn_b)
    assert stored_b.status == TurnStatus.PENDING_APPROVAL


@pytest.mark.asyncio
async def test_supersede_cancels_approval_of_a():
    """Superseded turn A has its approval cancelled."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="reply A")
    g = build_e2e([decision, decision])

    msg_a = VipInboundMessage(chat_id=100, text="primero", telegram_message_id=1, business_connection_id="bc-vip")
    turn_a = await g["orch"].handle_vip_message(msg_a)

    approval_a = await g["approvals"].get_by_turn(turn_a)
    assert approval_a is not None  # Was created

    msg_b = VipInboundMessage(chat_id=100, text="segundo", telegram_message_id=2, business_connection_id="bc-vip")
    await g["orch"].handle_vip_message(msg_b)

    approval_a_after = await g["approvals"].get_by_turn(turn_a)
    assert approval_a_after is not None
    assert approval_a_after.status == "cancelled"


@pytest.mark.asyncio
async def test_coalesce_burst():
    """Rapid VIP messages coalesce into one director turn."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola diana", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    assert len(g["director"].calls) == 1
    assert g["director"].calls[0].chat_id == 100
