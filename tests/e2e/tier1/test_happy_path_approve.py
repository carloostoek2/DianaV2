"""E2E: VIP message -> approve -> owner approves -> delivery."""

import pytest
from diana.application.ports import VipInboundMessage
from diana.cognitive.models import Decision, TurnStatus
from tests.e2e.conftest import make_eval, OWNER_ID
from tests.e2e.tier1.conftest import build_e2e, dispatch


@pytest.mark.asyncio
async def test_full_flow_vip_message_to_delivery():
    """VIP sends message -> cognitive pipeline -> approve -> owner approves -> delivered."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="Hola VIP!")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola diana", telegram_message_id=11, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    # Turn created and transitioned to PENDING_APPROVAL
    stored = await g["turns"].get(turn_id)
    assert stored is not None
    assert stored.status == TurnStatus.PENDING_APPROVAL

    # Owner notified with draft
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].draft_text == "Hola VIP!"

    # Message NOT sent yet (supervised mode)
    assert g["actuator"].send_count() == 0

    # Owner approves
    status = await dispatch("approve", turn_id, g)
    assert status == "approved"

    # Message delivered
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "Hola VIP!"

    # Turn transitioned to DELIVERED
    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.DELIVERED


@pytest.mark.asyncio
async def test_approve_creates_pending_approval_state():
    """Approve decision transitions turn to PENDING_APPROVAL and creates approval record."""
    decision = Decision(action="approve", reason="good", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.PENDING_APPROVAL

    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None
    assert approval.draft_text == "reply"


@pytest.mark.asyncio
async def test_owner_approve_delivers_and_transitions():
    """Owner approve callback delivers message and transitions to DELIVERED."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="respuesta")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    status = await dispatch("approve", turn_id, g)
    assert status == "approved"
    assert g["actuator"].send_count() == 1

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.DELIVERED


@pytest.mark.asyncio
async def test_approve_twice_second_returns_stale():
    """Approving an already-delivered turn returns stale."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="respuesta")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    status1 = await dispatch("approve", turn_id, g)
    assert status1 == "approved"

    # Second approve on terminal turn
    status2 = await dispatch("approve", turn_id, g)
    assert status2 == "stale"


@pytest.mark.asyncio
async def test_non_owner_approve_rejected():
    """Non-owner actor cannot approve."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="respuesta")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    status = await dispatch("approve", turn_id, g, actor_id=999999)
    assert status == "forbidden"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_draft_notification_contains_turn_id_and_text():
    """Owner draft notification includes the turn context."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="Hola, como estas?")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola diana", telegram_message_id=11, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    assert len(g["notifier"].drafts) == 1
    draft = g["notifier"].drafts[0]
    assert draft.draft_text == "Hola, como estas?"
    assert draft.turn_id == turn_id
