"""E2E: approve -> owner corrects -> staging -> re-delivery."""

import pytest
from diana.application.ports import VipInboundMessage
from diana.cognitive.models import Decision, TurnStatus
from tests.e2e.conftest import make_eval, OWNER_ID
from tests.e2e.tier1.conftest import build_e2e, dispatch


@pytest.mark.asyncio
async def test_correct_starts_session():
    """Correct callback on pending approval starts a correction session."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="original")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    status = await dispatch("correct", turn_id, g)
    assert status == "awaiting_correct"

    session_turn_id = g["sessions"].get(OWNER_ID)
    assert session_turn_id is not None
    assert session_turn_id == turn_id


@pytest.mark.asyncio
async def test_correct_with_text_delivers_corrected():
    """Correction with free text delivers the corrected message."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="original")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    await dispatch("correct", turn_id, g)
    result = await g["admin"].handle_correct(turn_id, "texto corregido", actor_id=OWNER_ID)
    assert result is not None

    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "texto corregido"


@pytest.mark.asyncio
async def test_correct_on_non_pending_returns_stale():
    """Correct on a non-pending turn returns stale."""
    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    await dispatch("approve", turn_id, g)
    assert (await g["turns"].get(turn_id)).status == TurnStatus.DELIVERED

    status = await dispatch("correct", turn_id, g)
    assert status == "stale_already_sent"
