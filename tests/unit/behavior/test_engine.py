"""BehaviorEngine: human-like delivery sequence + mid-flight cancel."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from diana.application.memory import InMemoryPendingDeliveryStore
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.behavior.ports import DeliveryContext


@pytest.fixture
def engine_bundle() -> tuple[BehaviorEngine, FakeTelegramActuator, InMemoryPendingDeliveryStore, ImmediateClock]:
    actuator = FakeTelegramActuator()
    store = InMemoryPendingDeliveryStore()
    clock = ImmediateClock()
    policy = FixedDelayPolicy(initial=0.05, typing=0.02)
    engine = BehaviorEngine(
        actuator,
        store,
        clock=clock,
        delay_policy=policy,
    )
    return engine, actuator, store, clock


def _ctx(**overrides: object) -> DeliveryContext:
    data: dict = {
        "chat_id": 10,
        "business_connection_id": "bc-1",
        "telegram_message_id": 99,
    }
    data.update(overrides)
    return DeliveryContext(**data)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_happy_path_sequence_order(
    engine_bundle: tuple,
) -> None:
    engine, actuator, store, clock = engine_bundle
    turn_id = uuid4()
    result = await engine.deliver(["hola"], _ctx(), turn_id)

    assert result.success is True
    assert result.cancelled is False
    assert result.message_ids == [1]
    assert [c["op"] for c in actuator.calls] == [
        "read_business_message",
        "send_chat_action",
        "send_message",
    ]
    assert clock.sleeps == [0.05, 0.02]
    pending = await store.list_pending()
    assert pending == []
    # delivery marked done
    all_rows = await store.list_all()
    assert len(all_rows) == 1
    assert all_rows[0].status == "done"


@pytest.mark.asyncio
async def test_multi_text_sends_each(
    engine_bundle: tuple,
) -> None:
    engine, actuator, _, _ = engine_bundle
    result = await engine.deliver(["a", "b", "c"], _ctx(), uuid4())
    assert result.success is True
    assert result.message_ids == [1, 2, 3]
    sends = [c for c in actuator.calls if c["op"] == "send_message"]
    assert [s["text"] for s in sends] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_cancel_pending_during_delay_no_send() -> None:
    actuator = FakeTelegramActuator()
    store = InMemoryPendingDeliveryStore()

    class SlowClock:
        def now(self):
            from datetime import UTC, datetime

            return datetime.now(UTC)

        async def sleep(self, seconds: float) -> None:
            await asyncio.sleep(0.2)

    engine = BehaviorEngine(
        actuator,
        store,
        clock=SlowClock(),
        delay_policy=FixedDelayPolicy(initial=10.0, typing=0.0),
    )
    turn_id = uuid4()
    task = asyncio.create_task(engine.deliver(["nope"], _ctx(), turn_id))
    await asyncio.sleep(0.05)
    await engine.cancel_pending(10)
    result = await task
    assert result.cancelled is True or result.success is False
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows
    assert all(r.status == "cancelled" for r in rows)


@pytest.mark.asyncio
async def test_cancel_idempotent(
    engine_bundle: tuple,
) -> None:
    engine, _, _, _ = engine_bundle
    await engine.cancel_pending(123)
    await engine.cancel_pending(123)  # must not raise


@pytest.mark.asyncio
async def test_missing_business_connection_id_fail_closed(
    engine_bundle: tuple,
) -> None:
    engine, actuator, store, _ = engine_bundle
    result = await engine.deliver(
        ["x"],
        DeliveryContext(chat_id=1, business_connection_id=""),
        uuid4(),
    )
    assert result.success is False
    assert result.error
    assert actuator.send_count() == 0
    assert await store.list_all() == []


@pytest.mark.asyncio
async def test_whitespace_business_connection_id_fail_closed(
    engine_bundle: tuple,
) -> None:
    engine, actuator, _, _ = engine_bundle
    result = await engine.deliver(
        ["x"],
        DeliveryContext(chat_id=1, business_connection_id="   "),
        uuid4(),
    )
    assert result.success is False
    assert actuator.send_count() == 0
