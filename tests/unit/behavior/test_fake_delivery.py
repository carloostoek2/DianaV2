"""FakeTelegramActuator records ordered I/O without network."""

from __future__ import annotations

import pytest

from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock


@pytest.mark.asyncio
async def test_fake_actuator_records_ordered_calls() -> None:
    actuator = FakeTelegramActuator()
    await actuator.read_business_message(10, 99, business_connection_id="bc-1")
    await actuator.send_chat_action(10, "typing", business_connection_id="bc-1")
    mid = await actuator.send_message(10, "hola", business_connection_id="bc-1")

    assert mid == 1
    assert [c["op"] for c in actuator.calls] == [
        "read_business_message",
        "send_chat_action",
        "send_message",
    ]
    assert actuator.calls[2]["text"] == "hola"
    assert actuator.calls[2]["business_connection_id"] == "bc-1"


@pytest.mark.asyncio
async def test_fake_actuator_increments_message_ids() -> None:
    actuator = FakeTelegramActuator(start_message_id=100)
    a = await actuator.send_message(1, "a", business_connection_id="bc")
    b = await actuator.send_message(1, "b", business_connection_id="bc")
    assert (a, b) == (100, 101)


@pytest.mark.asyncio
async def test_immediate_clock_and_fixed_delay_policy() -> None:
    clock = ImmediateClock()
    policy = FixedDelayPolicy(initial=0.0, typing=0.0)
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    clock.sleep = record_sleep  # type: ignore[method-assign]
    await clock.sleep(policy.initial_delay_seconds())
    await clock.sleep(policy.typing_duration_seconds("hi"))
    assert slept == [0.0, 0.0]
    assert policy.initial_delay_seconds() == 0.0
