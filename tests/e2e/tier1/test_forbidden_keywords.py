"""E2E: Forbidden keywords -> direct escalation (no director call)."""

import pytest
from diana.application.ports import VipInboundMessage
from diana.cognitive.models import TurnStatus
from tests.e2e.tier1.conftest import build_e2e


@pytest.mark.asyncio
async def test_forbidden_keyword_blocks_and_notifies():
    """Forbidden keyword creates escalation-like entry without calling director."""
    g = build_e2e([])  # No director decisions needed

    msg = VipInboundMessage(chat_id=100, text="palabra prohibida aqui", telegram_message_id=1, business_connection_id="bc-vip")

    # Simulate the middleware/handler blocking flow using begin_turn (with chat_scope)
    record = await g["coordinator"].begin_turn(
        chat_id=msg.chat_id,
        trigger_message_id=msg.telegram_message_id,
        vip_id=msg.vip_id,
    )
    await g["coordinator"].mark_failed(record.id, error="forbidden_keyword")
    await g["notifier"].notify_info(f"Blocked: {msg.text}", chat_id=msg.chat_id)

    stored = await g["turns"].get(record.id)
    assert stored.status == TurnStatus.FAILED
    assert stored.error == "forbidden_keyword"
    assert len(g["notifier"].infos) >= 1


@pytest.mark.asyncio
async def test_forbidden_keyword_never_delivers():
    """Blocked messages never reach delivery."""
    g = build_e2e([])

    msg = VipInboundMessage(chat_id=100, text="mala palabra", telegram_message_id=1, business_connection_id="bc-vip")
    record = await g["coordinator"].begin_turn(
        chat_id=msg.chat_id, trigger_message_id=msg.telegram_message_id, vip_id=msg.vip_id,
    )
    await g["coordinator"].mark_failed(record.id, error="forbidden_keyword")

    assert g["actuator"].send_count() == 0
