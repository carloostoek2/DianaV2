"""E2E: VIP message -> consult_doctrine -> gray zone query."""

import pytest
from uuid import uuid4
from diana.application.ports import VipInboundMessage
from diana.cognitive.models import Decision, TurnStatus
from tests.e2e.conftest import make_eval, OWNER_ID
from tests.e2e.tier1.conftest import build_e2e, FakeGrayZone


@pytest.mark.asyncio
async def test_consult_doctrine_creates_query_and_transitions():
    """Consult doctrine creates a gray zone query and transitions to GRAY_ZONE."""
    decision = Decision(action="consult_doctrine", reason="ambiguous policy", evaluation=make_eval(), draft_text="tentative reply")
    gz = FakeGrayZone()
    g = build_e2e([decision], feature_gray_zone_enabled=True, gray_zone=gz)

    msg = VipInboundMessage(chat_id=100, text="pregunta dificil", telegram_message_id=1, business_connection_id="bc-vip", vip_id=uuid4())
    turn_id = await g["orch"].handle_vip_message(msg)

    stored = await g["turns"].get(turn_id)
    assert stored.status == TurnStatus.GRAY_ZONE
    assert len(gz.queries) == 1
    assert gz.queries[0]["turn_id"] == turn_id


@pytest.mark.asyncio
async def test_consult_doctrine_without_feature_flag_raises():
    """Consult doctrine without feature flag raises RuntimeError."""
    decision = Decision(action="consult_doctrine", reason="ambiguous", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision], feature_gray_zone_enabled=False, gray_zone=None)

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip", vip_id=uuid4())
    with pytest.raises(RuntimeError, match="gray zone feature is disabled"):
        await g["orch"].handle_vip_message(msg)


@pytest.mark.asyncio
async def test_consult_doctrine_without_service_raises():
    """Consult doctrine without GrayZoneService raises RuntimeError."""
    decision = Decision(action="consult_doctrine", reason="ambiguous", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision], feature_gray_zone_enabled=True, gray_zone=None)

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip", vip_id=uuid4())
    with pytest.raises(RuntimeError, match="GrayZoneService is not injected"):
        await g["orch"].handle_vip_message(msg)


@pytest.mark.asyncio
async def test_consult_doctrine_sends_notification():
    """Consult doctrine sends doctrine notification to owner."""
    decision = Decision(action="consult_doctrine", reason="ambiguous", evaluation=make_eval(), draft_text="tentative")
    gz = FakeGrayZone()
    g = build_e2e([decision], feature_gray_zone_enabled=True, gray_zone=gz)

    msg = VipInboundMessage(chat_id=100, text="pregunta", telegram_message_id=1, business_connection_id="bc-vip", vip_id=uuid4())
    turn_id = await g["orch"].handle_vip_message(msg)

    assert len(g["notifier"].doctrines) == 1
    assert g["notifier"].doctrines[0].turn_id == turn_id
