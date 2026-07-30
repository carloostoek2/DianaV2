"""E2E: VIP message -> escalate -> owner notified."""

import pytest
from diana.application.ports import VipInboundMessage
from diana.cognitive.models import Decision, TurnStatus
from tests.e2e.conftest import make_eval
from tests.e2e.tier1.conftest import build_e2e, dispatch


@pytest.mark.asyncio
async def test_escalate_transitions_to_escalated():
    """Escalate decision transitions turn to ESCALATED."""
    decision = Decision(action="escalate", reason="risk alto", evaluation=make_eval(), draft_text="")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="problema", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_escalate_notifies_owner_with_escalation_payload():
    """Escalate sends escalation notification to owner."""
    decision = Decision(action="escalate", reason="critical issue", evaluation=make_eval(), draft_text="")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="emergencia", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    assert len(g["notifier"].escalations) == 1
    esc = g["notifier"].escalations[0]
    assert esc.turn_id == turn_id


@pytest.mark.asyncio
async def test_escalate_never_delivers():
    """Escalated messages are never sent to VIP."""
    decision = Decision(action="escalate", reason="risk", evaluation=make_eval(), draft_text="")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    await g["orch"].handle_vip_message(msg)

    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_owner_escalate_callback_on_pending_approval_cancels():
    """Owner escalates a pending approval turn -> ESCALATED, delivery cancelled."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)
    assert (await g["turns"].get(turn_id)).status == TurnStatus.PENDING_APPROVAL

    status = await dispatch("escalate", turn_id, g)
    assert status == "escalated"

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.ESCALATED
    assert g["actuator"].send_count() == 0
