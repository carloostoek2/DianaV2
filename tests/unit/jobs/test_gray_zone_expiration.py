"""GrayZoneExpirationJob — periodic expiration loop tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from diana.jobs.gray_zone_expiration import GrayZoneExpirationJob
from diana.application.turn_coordinator import ChatLockTimeoutError


class FakeGrayZone:
    """Fake GrayZoneService that records calls and can simulate results."""

    def __init__(self) -> None:
        self.expire_calls: list[list[object]] = []
        self._results: list[list[object]] = []
        self._error_on: set[int] = set()
        self.reopen_calls: list[object] = []

    async def reopen_query(self, query_id: object) -> bool:
        self.reopen_calls.append(query_id)
        return True

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
        self._failures: set[UUID] = set()

    def fail_on(self, turn_id: UUID) -> None:
        self._failures.add(turn_id)

    async def transition(self, turn_id: UUID, status: str) -> None:
        self.transitions.append((turn_id, status))
        if turn_id in self._failures:
            msg = f"simulated transition error for {turn_id}"
            raise RuntimeError(msg)


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
        self._denials: set[UUID] = set()
        self._lock_timeouts: set[UUID] = set()

    def fail_on(self, turn_id: UUID) -> None:
        self._failures.add(turn_id)

    def deny_on(self, turn_id: UUID) -> None:
        """Simulate a fail-soft False (e.g. legacy row without bc)."""
        self._denials.add(turn_id)

    def lock_timeout_on(self, turn_id: UUID) -> None:
        """Simulate ChatLockTimeoutError (lock contention with dx:/owner)."""
        self._lock_timeouts.add(turn_id)

    async def create_supervised_delivery_from_gray_zone(
        self, turn_id: UUID, row: object
    ) -> bool:
        self.supervised_calls.append((turn_id, row))
        if turn_id in self._failures:
            raise RuntimeError(f"simulated delivery error for {turn_id}")
        if turn_id in self._lock_timeouts:
            raise ChatLockTimeoutError(
                f"simulated lock timeout for chat of {turn_id}"
            )
        if turn_id in self._denials:
            return False
        return True


def make_expired_item(
    turn_id: UUID | None = None,
    *,
    draft: str | None = None,
    business_connection_id: str | None = None,
    query_id: UUID | None = None,
) -> SimpleNamespace:
    """Create a minimal object that looks like an expired GrayZoneQuery row."""
    item: dict = {
        "turn_id": turn_id or uuid4(),
        "id": query_id or uuid4(),
    }
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
    # The failed delivery falls back to the legacy escalate so the turn is
    # never left stuck in gray_zone; the healthy one stays pending approval.
    assert coordinator.transitions == [(failing_turn, "escalated")]


@pytest.mark.asyncio
async def test_expiry_with_draft_denied_falls_back_to_escalated() -> None:
    """Fail-soft False (e.g. legacy row without business_connection_id) → escalated.

    Guards the R-A regression: before the supervised-delivery path, every
    expired query escalated; a draft row that cannot become a PendingApproval
    must keep that guarantee instead of being stranded in gray_zone.
    """
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    admin = FakeAdmin()
    turn_id = uuid4()
    admin.deny_on(turn_id)
    gray_zone.add_result(
        [make_expired_item(turn_id, draft="texto", business_connection_id=None)]
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
    assert coordinator.transitions == [(turn_id, "escalated")]


@pytest.mark.asyncio
async def test_expiry_notification_reflects_actual_outcomes() -> None:
    """The grouped notification counts real outcomes, not row attributes."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    admin = FakeAdmin()
    delivered_turn = uuid4()
    denied_turn = uuid4()
    escalated_turn = uuid4()
    admin.deny_on(denied_turn)
    gray_zone.add_result(
        [
            make_expired_item(delivered_turn, draft="d1", business_connection_id="b1"),
            make_expired_item(denied_turn, draft="d2", business_connection_id=None),
            make_expired_item(escalated_turn, draft=""),
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

    assert coordinator.transitions == [
        (denied_turn, "escalated"),
        (escalated_turn, "escalated"),
    ]
    assert notifier.info_calls
    last_info = notifier.info_calls[-1]
    assert "1 pending approval" in last_info
    assert "2 escalated" in last_info
    assert "3 total" in last_info


@pytest.mark.asyncio
async def test_expiry_lock_timeout_is_failed_not_escalated() -> None:
    """ChatLockTimeoutError must NOT escalate (the lock holder may be mid-approval).

    Escalating a turn whose approval is being created by the dx: path would
    leave a waiting orphan on an escalated turn — count as failed and reopen
    the query so a later run retries.
    """
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    admin = FakeAdmin()
    turn_id = uuid4()
    query_id = uuid4()
    admin.lock_timeout_on(turn_id)
    gray_zone.add_result(
        [
            make_expired_item(
                turn_id, draft="texto", business_connection_id="bc1",
                query_id=query_id,
            )
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

    assert len(admin.supervised_calls) == 1
    assert coordinator.transitions == []  # never escalated on lock contention
    assert gray_zone.reopen_calls == [query_id]  # reopened for a later run
    assert notifier.info_calls
    assert "1 failed" in notifier.info_calls[-1]


@pytest.mark.asyncio
async def test_expiry_double_failure_reopens_query_for_retry() -> None:
    """Delivery AND escalate both fail → query reopened so a later run retries."""
    gray_zone = FakeGrayZone()
    coordinator = FakeCoordinator()
    notifier = FakeNotifier()
    admin = FakeAdmin()
    turn_id = uuid4()
    query_id = uuid4()
    admin.deny_on(turn_id)
    coordinator.fail_on(turn_id)
    gray_zone.add_result(
        [
            make_expired_item(
                turn_id,
                draft="texto",
                business_connection_id=None,
                query_id=query_id,
            )
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

    assert len(admin.supervised_calls) == 1
    assert coordinator.transitions == [(turn_id, "escalated")]  # attempted
    assert gray_zone.reopen_calls == [query_id]
    assert notifier.info_calls
    assert "1 failed" in notifier.info_calls[-1]
