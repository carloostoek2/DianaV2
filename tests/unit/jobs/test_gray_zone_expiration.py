"""GrayZoneExpirationJob — periodic expiration loop tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from diana.jobs.gray_zone_expiration import GrayZoneExpirationJob


class FakeGrayZone:
    """Fake GrayZoneService that records calls and can simulate results."""

    def __init__(self) -> None:
        self.expire_calls: list[list[object]] = []
        self._results: list[list[object]] = []
        self._error_on: set[int] = set()

    def add_result(self, items: list[object]) -> None:
        """Register the next result list for expire_old_queries.

        Items should be SimpleNamespace objects with a ``turn_id`` UUID
        attribute when testing escalation behavior.
        """
        self._results.append(items)

    def error_on_call(self, call_index: int) -> None:
        self._error_on.add(call_index)

    async def expire_old_queries(self) -> list[object]:
        call_index = len(self.expire_calls)
        self.expire_calls.append([])
        if call_index in self._error_on:
            msg = f"simulated error on call {call_index}"
            raise RuntimeError(msg)
        if call_index < len(self._results):
            result = self._results[call_index]
        else:
            result = []
        self.expire_calls[-1] = result
        return result


class FakeCoordinator:
    """Record transitions without real DB."""

    def __init__(self) -> None:
        self.transitions: list[tuple[UUID, str]] = []

    async def transition(self, turn_id: UUID, status: str) -> None:
        self.transitions.append((turn_id, status))


class FakeNotifier:
    """Record notify_info calls."""

    def __init__(self) -> None:
        self.info_calls: list[str] = []

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        self.info_calls.append(text)


class FakeAdmin:
    """Record create_supervised_delivery_from_gray_zone calls."""

    def __init__(self) -> None:
        self.supervised_calls: list[tuple[UUID, object]] = []
        self._failures: set[UUID] = set()

    def fail_on(self, turn_id: UUID) -> None:
        self._failures.add(turn_id)

    async def create_supervised_delivery_from_gray_zone(
        self, turn_id: UUID, row: object
    ) -> bool:
        self.supervised_calls.append((turn_id, row))
        if turn_id in self._failures:
            raise RuntimeError(f"simulated delivery error for {turn_id}")
        return True


def make_expired_item(
    turn_id: UUID | None = None,
    *,
    draft: str | None = None,
    business_connection_id: str | None = None,
) -> SimpleNamespace:
    """Create a minimal object that looks like an expired GrayZoneQuery row."""
    item: dict = {"turn_id": turn_id or uuid4()}
    if draft is not None:
        item["draft"] = draft
    if business_connection_id is not None:
        item["business_connection_id"] = business_connection_id
    return SimpleNamespace(**item)


@pytest.mark.asyncio
async def test_job_calls_expire_on_interval() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    turn_id = uuid4()
    gray_zone.add_result([make_expired_item(turn_id)])
    job = GrayZoneExpirationJob(
        gray_zone,
        coordinator=coordinator,
        notifier=notifier,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert len(gray_zone.expire_calls) >= 1
    for call_result in gray_zone.expire_calls:
        assert isinstance(call_result, list)
    # Verify escalation happened for expired items
    assert len(coordinator.transitions) >= 1
    assert coordinator.transitions[0] == (turn_id, "escalated")
    # Verify notification was fired
    assert len(notifier.info_calls) >= 1


@pytest.mark.asyncio
async def test_job_handles_exceptions_gracefully() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    gray_zone.error_on_call(0)
    job = GrayZoneExpirationJob(
        gray_zone,
        coordinator=coordinator,
        notifier=notifier,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    # After error, the loop should continue and try again
    assert len(gray_zone.expire_calls) >= 2


@pytest.mark.asyncio
async def test_job_logs_expired_count() -> None:
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    items = [make_expired_item() for _ in range(3)]
    gray_zone.add_result(items)
    job = GrayZoneExpirationJob(
        gray_zone,
        coordinator=coordinator,
        notifier=notifier,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.08)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert len(gray_zone.expire_calls) >= 1
    first_call = gray_zone.expire_calls[0]
    assert len(first_call) == 3
    assert len(coordinator.transitions) == 3


@pytest.mark.asyncio
async def test_pre_stopped_job_does_not_run() -> None:
    """Calling stop() before start() should prevent any iteration."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    job = GrayZoneExpirationJob(
        gray_zone,
        coordinator=coordinator,
        notifier=notifier,
        interval_seconds=0.05,
    )

    await job.stop()
    await job.start()

    assert len(gray_zone.expire_calls) == 0
    assert len(coordinator.transitions) == 0


# --- R-A: expiry with draft → supervised delivery (admin injected) ---


@pytest.mark.asyncio
async def test_expiry_with_draft_calls_supervised_delivery() -> None:
    """Draft + admin → supervised delivery called once, no escalated transition."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    admin = FakeAdmin()
    turn_id = uuid4()
    gray_zone.add_result(
        [make_expired_item(turn_id, draft="texto", business_connection_id="bc123")]
    )
    job = GrayZoneExpirationJob(
        gray_zone,
        coordinator=coordinator,
        notifier=notifier,
        admin=admin,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert len(admin.supervised_calls) == 1
    called_turn_id, called_row = admin.supervised_calls[0]
    assert called_turn_id == turn_id
    assert called_row.draft == "texto"
    assert coordinator.transitions == []


@pytest.mark.asyncio
async def test_expiry_without_draft_still_escalates_with_admin() -> None:
    """Draft empty/None → escalated even when admin is injected."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    admin = FakeAdmin()
    turn_id = uuid4()
    gray_zone.add_result([make_expired_item(turn_id, draft="")])
    job = GrayZoneExpirationJob(
        gray_zone,
        coordinator=coordinator,
        notifier=notifier,
        admin=admin,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert admin.supervised_calls == []
    assert coordinator.transitions == [(turn_id, "escalated")]


@pytest.mark.asyncio
async def test_expiry_with_draft_admin_none_falls_back_to_escalated() -> None:
    """admin=None (flag OFF) → draft items still escalate (safe fallback)."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    turn_id = uuid4()
    gray_zone.add_result(
        [make_expired_item(turn_id, draft="texto", business_connection_id="bc1")]
    )
    job = GrayZoneExpirationJob(
        gray_zone,
        coordinator=coordinator,
        notifier=notifier,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert coordinator.transitions == [(turn_id, "escalated")]


@pytest.mark.asyncio
async def test_expiry_supervised_error_does_not_break_loop() -> None:
    """A failing supervised delivery must not stop the remaining items."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    admin = FakeAdmin()
    failing_turn = uuid4()
    ok_turn = uuid4()
    admin.fail_on(failing_turn)
    gray_zone.add_result(
        [
            make_expired_item(failing_turn, draft="d1", business_connection_id="b1"),
            make_expired_item(ok_turn, draft="d2", business_connection_id="b2"),
        ]
    )
    job = GrayZoneExpirationJob(
        gray_zone,
        coordinator=coordinator,
        notifier=notifier,
        admin=admin,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    # Both items were attempted; the failing one did not derail the second.
    assert len(admin.supervised_calls) == 2
    assert {c[0] for c in admin.supervised_calls} == {failing_turn, ok_turn}
    assert coordinator.transitions == []
