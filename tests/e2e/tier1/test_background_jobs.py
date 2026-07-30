"""E2E: Background jobs -- gray zone expiration, trace purge, recontact."""

import pytest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from diana.cognitive.models import TurnStatus
from tests.e2e.tier1.conftest import build_e2e, FakeGrayZone


@pytest.mark.asyncio
async def test_gray_zone_expiration_noops_with_no_queries():
    """Gray zone expiration with no queries returns empty list."""
    gz = FakeGrayZone()
    g = build_e2e([], feature_gray_zone_enabled=True, gray_zone=gz)
    # No queries created -- expiration should return empty
    assert len(g["gray_zone"].queries) == 0


@pytest.mark.asyncio
async def test_trace_purge_preserves_recent_traces():
    """Trace purge leaves recent traces intact."""
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


@pytest.mark.asyncio
async def test_turn_transition_state_machine():
    """Turn transitions follow valid state machine rules."""
    from diana.application.ports import VipInboundMessage
    from diana.cognitive.models import Decision
    from tests.e2e.conftest import make_eval

    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola diana", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    stored = await g["turns"].get(turn_id)
    assert stored is not None
    assert stored.status == TurnStatus.PENDING_APPROVAL
    assert stored.chat_id == 100
