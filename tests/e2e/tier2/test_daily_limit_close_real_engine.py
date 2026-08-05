"""E2E: F4-02 closing reply through a REAL BehaviorEngine + Postgres FK.

Proves the FIX-1 production wire end-to-end against real Postgres: a real
``BehaviorEngine`` with ``TurnStoreStatusReader(SqlTurnStore)`` liveness gate,
a minted ``promo_pending`` turn, and the ``pending_deliveries.turn_id``
foreign key (the insert resolves — no integrity error). The orchestrator unit
tests inject a ``_CapturingDeliverer`` spy that bypasses the engine; this test
exercises the actual engine path the production wire uses for message #21.

Cleanup: the minted turn and its delivery row are DELETEd in ``finally`` so
other tier2 tests are never polluted.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from diana.application.ports import DeliveryContext, TurnRecord
from diana.application.turn_orchestrator import ATENCION_DAILY_LIMIT_CLOSE
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import (
    FakeTelegramActuator,
    FixedDelayPolicy,
    ImmediateClock,
)
from diana.cognitive.models import TurnStatus
from diana.composition import TurnStoreStatusReader
from diana.infrastructure.db.repositories.deliveries import SqlPendingDeliveryStore
from diana.infrastructure.db.repositories.turns import SqlTurnStore

_CHAT = 988222

_DELETE_DELIVERY = text("DELETE FROM pending_deliveries WHERE turn_id = :turn_id")
_DELETE_TURN = text("DELETE FROM turns WHERE id = :turn_id")


@pytest.mark.db
@pytest.mark.asyncio
async def test_daily_limit_close_delivers_through_real_engine(engine) -> None:
    """The close is deliverable in production: real engine + FK + liveness gate."""
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    turns = SqlTurnStore(sf)
    deliveries = SqlPendingDeliveryStore(sf)
    act = FakeTelegramActuator()
    behavior = BehaviorEngine(
        act,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=TurnStoreStatusReader(turns),
    )
    turn = await turns.create(
        TurnRecord(
            id=uuid4(),
            chat_id=_CHAT,
            status=TurnStatus.PROMO_PENDING.value,
            vip_id=None,
        )
    )
    try:
        ctx = DeliveryContext(
            chat_id=_CHAT,
            business_connection_id="bc-limit-close",
            vip_id=None,
            mode="autonomous",
            is_frozen=False,
            telegram_message_id=12345,
            skip_initial_delay=True,
        )
        result = await behavior.deliver(
            [ATENCION_DAILY_LIMIT_CLOSE],
            ctx,
            turn.id,
            decision=None,
        )
        assert result.success is True
        # FakeTelegramActuator recorded the send (op=send_message, text).
        sent = [c for c in act.calls if c["op"] == "send_message"]
        assert sent, "engine never sent the closing reply"
        assert sent[-1]["text"] == ATENCION_DAILY_LIMIT_CLOSE
        assert sent[-1]["chat_id"] == _CHAT
        # pending_deliveries row with turn_id == turn.id (FK resolved = no
        # integrity error; the synthetic-uuid4 bug would have raised here).
        async with engine.begin() as conn:
            delivery_turn_id = (
                await conn.execute(
                    text(
                        "SELECT turn_id FROM pending_deliveries "
                        "WHERE turn_id = :turn_id"
                    ),
                    {"turn_id": turn.id},
                )
            ).scalar_one()
        assert delivery_turn_id == turn.id
        # The engine does NOT transition the turn (the orchestrator does);
        # this test proves the engine path only.
        after = await turns.get(turn.id)
        assert after is not None
        assert after.status == TurnStatus.PROMO_PENDING.value
    finally:
        async with engine.begin() as conn:
            await conn.execute(_DELETE_DELIVERY, {"turn_id": turn.id})
            await conn.execute(_DELETE_TURN, {"turn_id": turn.id})
