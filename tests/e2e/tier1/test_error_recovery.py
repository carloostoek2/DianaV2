"""E2E: Director exceptions -> turn failed -> owner notified."""

import pytest
from diana.application.ports import VipInboundMessage
from diana.cognitive.exceptions import (
    AnalystSchemaInvalidError,
    EvaluatorSchemaInvalidError,
    ContextExceedsLimitError,
    GeneratorEmptyOutputError,
)
from diana.cognitive.models import TurnStatus
from tests.e2e.tier1.conftest import build_e2e


class FailingDirector:
    """Director that raises a specific exception on handle_turn."""
    def __init__(self, exc: Exception):
        self._exc = exc
        self.calls = []

    async def handle_turn(self, turn):
        self.calls.append(turn)
        raise self._exc


@pytest.mark.asyncio
async def test_analyst_schema_invalid_marks_failed():
    """AnalystSchemaInvalidError is caught, turn marked FAILED, owner notified."""
    d = FailingDirector(AnalystSchemaInvalidError("bad schema"))
    g = build_e2e([], behavior_override=None)
    g["orch"]._director = d

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    assert turn_id is not None
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "failed"
    assert turn.error == "analista_schema_invalido"
    assert any(
        "analista_schema_invalido" in info[0]
        for info in g["notifier"].infos
    )


@pytest.mark.asyncio
async def test_evaluator_schema_invalid_marks_failed():
    """EvaluatorSchemaInvalidError is caught, turn marked FAILED, owner notified."""
    d = FailingDirector(EvaluatorSchemaInvalidError("bad eval"))
    g = build_e2e([], behavior_override=None)
    g["orch"]._director = d

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    turn_id = await g["orch"].handle_vip_message(msg)

    assert turn_id is not None
    turn = await g["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "failed"
    assert turn.error == "evaluador_schema_invalido"
    assert any(
        "evaluador_schema_invalido" in info[0]
        for info in g["notifier"].infos
    )


@pytest.mark.asyncio
async def test_generic_exception_marks_failed():
    """Generic exception marks turn FAILED with error string."""
    d = FailingDirector(RuntimeError("something broke"))
    g = build_e2e([], behavior_override=None)
    g["orch"]._director = d

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="bc-vip")
    with pytest.raises(RuntimeError):
        await g["orch"].handle_vip_message(msg)


@pytest.mark.asyncio
async def test_missing_business_connection_id_raises():
    """Missing business_connection_id raises ValueError."""
    from diana.cognitive.models import Decision
    from tests.e2e.conftest import make_eval

    decision = Decision(action="approve", reason="ok", evaluation=make_eval(), draft_text="reply")
    g = build_e2e([decision])

    msg = VipInboundMessage(chat_id=100, text="hola", telegram_message_id=1, business_connection_id="")
    with pytest.raises(ValueError, match="business_connection_id"):
        await g["orch"].handle_vip_message(msg)
