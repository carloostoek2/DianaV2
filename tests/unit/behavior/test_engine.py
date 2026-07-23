"""BehaviorEngine: human-like delivery sequence + mid-flight cancel."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from diana.application.memory import InMemoryPendingDeliveryStore
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import (
    AlwaysLiveTurnStatusReader,
    FakeTelegramActuator,
    FixedDelayPolicy,
    FlakySendActuator,
    ImmediateClock,
    SequenceTurnStatusReader,
)
from diana.behavior.ports import DeliveryContext, TransientSendError


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
        turn_status=AlwaysLiveTurnStatusReader(),
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


# --- I.2 mode enum (Task 1) ---


def test_delivery_context_accepts_autonomous_mode() -> None:
    ctx = DeliveryContext(
        chat_id=1, business_connection_id="bc", mode="autonomous"
    )
    assert ctx.mode == "autonomous"


def test_delivery_context_accepts_fake_delivery_mode() -> None:
    ctx = DeliveryContext(
        chat_id=1, business_connection_id="bc", mode="fake_delivery"
    )
    assert ctx.mode == "fake_delivery"


def test_delivery_context_rejects_invalid_mode() -> None:
    with pytest.raises(ValidationError):
        DeliveryContext(chat_id=1, business_connection_id="bc", mode="nope")  # type: ignore[arg-type]


def test_task1_fakes_importable() -> None:
    assert AlwaysLiveTurnStatusReader is not None
    assert SequenceTurnStatusReader is not None
    assert FlakySendActuator is not None
    assert issubclass(TransientSendError, Exception)


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
    assert result.cancelled is True
    assert result.success is False
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows
    assert all(r.status == "cancelled" for r in rows)


@pytest.mark.asyncio
async def test_cancelled_status_not_overwritten_by_done() -> None:
    store = InMemoryPendingDeliveryStore()
    from datetime import UTC, datetime

    from diana.application.ports import DeliveryRecord

    rec = DeliveryRecord(
        id=uuid4(),
        chat_id=1,
        business_connection_id="bc",
        texts=["x"],
        decision={},
        scheduled_at=datetime.now(UTC),
        status="pending",
        turn_id=uuid4(),
    )
    await store.insert_pending(rec)
    assert await store.update_status(rec.id, "delivering") is True
    assert await store.update_status(rec.id, "cancelled") is True
    assert await store.update_status(rec.id, "done") is False
    got = await store.get(rec.id)
    assert got is not None and got.status == "cancelled"


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


# --- I.4 pre-send gate / retries / I.2 fake_delivery (Task 2) ---


def _engine(
    actuator: FakeTelegramActuator | FlakySendActuator | None = None,
    *,
    turn_status: object | None = None,
    max_send_attempts: int = 3,
    retry_backoff_seconds: float = 0.05,
    store: InMemoryPendingDeliveryStore | None = None,
    clock: ImmediateClock | None = None,
    initial: float = 0.05,
    typing: float = 0.02,
) -> tuple[BehaviorEngine, FakeTelegramActuator | FlakySendActuator, InMemoryPendingDeliveryStore, ImmediateClock]:
    act = actuator or FakeTelegramActuator()
    st = store or InMemoryPendingDeliveryStore()
    ck = clock or ImmediateClock()
    engine = BehaviorEngine(
        act,
        st,
        clock=ck,
        delay_policy=FixedDelayPolicy(initial=initial, typing=typing),
        turn_status=turn_status if turn_status is not None else AlwaysLiveTurnStatusReader(),
        max_send_attempts=max_send_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    return engine, act, st, ck


@pytest.mark.asyncio
async def test_presend_superseded_aborts_without_send() -> None:
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader(["superseded"]),
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.cancelled is True
    assert result.success is False
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_presend_terminal_failed_aborts() -> None:
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader(["failed"]),
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is False
    assert result.cancelled is True
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_presend_missing_turn_aborts() -> None:
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader([None]),
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is False
    assert result.cancelled is True
    assert actuator.send_count() == 0
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_transient_then_success_within_budget() -> None:
    flaky = FlakySendActuator(fail_times=1)
    engine, _, _, clock = _engine(
        flaky, max_send_attempts=3, retry_backoff_seconds=0.05
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is True
    assert flaky.send_attempts >= 2
    assert flaky.send_count() == 1
    assert 0.05 in clock.sleeps  # retry backoff recorded


@pytest.mark.asyncio
async def test_transient_exhausted_returns_error() -> None:
    flaky = FlakySendActuator(always_fail=True)
    engine, _, store, _ = _engine(
        flaky, max_send_attempts=2, retry_backoff_seconds=0.01
    )
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is False
    assert result.cancelled is False
    assert result.error
    assert flaky.send_attempts == 2
    rows = await store.list_all()
    assert rows and rows[0].status == "error"


@pytest.mark.asyncio
async def test_permanent_error_no_retry() -> None:
    class BoomActuator(FakeTelegramActuator):
        def __init__(self) -> None:
            super().__init__()
            self.send_attempts = 0

        async def send_message(
            self,
            chat_id: int,
            text: str,
            *,
            business_connection_id: str,
        ) -> int:
            self.send_attempts += 1
            raise RuntimeError("permanent boom")

    boom = BoomActuator()
    engine, _, store, _ = _engine(boom, max_send_attempts=3)
    result = await engine.deliver(["hola"], _ctx(), uuid4())
    assert result.success is False
    assert boom.send_attempts == 1
    rows = await store.list_all()
    assert rows and rows[0].status == "error"


@pytest.mark.asyncio
async def test_fake_delivery_no_network_send() -> None:
    engine, actuator, store, clock = _engine(initial=0.05, typing=0.02)
    result = await engine.deliver(
        ["hola"],
        _ctx(mode="fake_delivery"),
        uuid4(),
    )
    assert result.success is True
    assert result.message_ids == []
    assert actuator.calls == []  # no read/typing/send
    assert clock.sleeps == [0.05]  # initial delay may still apply
    rows = await store.list_all()
    assert rows and rows[0].status == "done"


@pytest.mark.asyncio
async def test_fake_delivery_presend_abort() -> None:
    engine, actuator, store, _ = _engine(
        turn_status=SequenceTurnStatusReader(["superseded"]),
    )
    result = await engine.deliver(
        ["hola"],
        _ctx(mode="fake_delivery"),
        uuid4(),
    )
    assert result.success is False
    assert result.cancelled is True
    assert actuator.calls == []
    rows = await store.list_all()
    assert rows and rows[0].status == "cancelled"
