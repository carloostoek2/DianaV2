"""E2E: SqlEscalationStore reads against real PostgreSQL."""
import pytest
from uuid import uuid4

from diana.application.ports import TurnRecord
from diana.infrastructure.db.repositories.escalations import SqlEscalationStore
from diana.infrastructure.db.repositories.turns import SqlTurnStore


async def _turn(session_factory, chat_id: int):
    """Escalation rows reference a turn (FK), so every case mints one."""
    turn_id = uuid4()
    await SqlTurnStore(session_factory).create(
        TurnRecord(id=turn_id, chat_id=chat_id, status="escalated")
    )
    return turn_id


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_motivo_returns_the_persisted_reason(session_factory):
    repo = SqlEscalationStore(session_factory)
    turn_id = await _turn(session_factory, 320)

    await repo.create(
        turn_id,
        tipo="semantica",
        motivo="safety_below_threshold",
        business_connection_id="bc-1",
    )

    assert await repo.get_motivo(turn_id) == "safety_below_threshold"
    assert await repo.get_business_connection_id(turn_id) == "bc-1"


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_motivo_is_none_without_a_row(session_factory):
    assert await SqlEscalationStore(session_factory).get_motivo(uuid4()) is None


@pytest.mark.db
@pytest.mark.asyncio
async def test_get_motivo_keeps_a_null_motivo(session_factory):
    """A deterministic escalation may carry no motivo: never invented."""
    repo = SqlEscalationStore(session_factory)
    turn_id = await _turn(session_factory, 321)

    await repo.create(turn_id, tipo="pago_precio", motivo=None)

    assert await repo.get_motivo(turn_id) is None
