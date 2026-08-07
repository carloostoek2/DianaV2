"""AgentDataPurgeJob — periodic multi-store TTL purge loop tests."""

from __future__ import annotations

import asyncio

import pytest

from diana.jobs.agent_data_purge import AgentDataPurgeJob


class FakePurgeStore:
    """Fake store recording purge_expired(ttl_days) calls."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.ttl_calls: list[int] = []
        self._results: list[int] = []
        self._error_on: set[int] = set()

    def add_result(self, deleted: int) -> None:
        self._results.append(deleted)

    def error_on_call(self, call_index: int) -> None:
        self._error_on.add(call_index)

    async def purge_expired(self, ttl_days: int) -> int:
        call_index = len(self.ttl_calls)
        self.ttl_calls.append(ttl_days)
        if call_index in self._error_on:
            raise RuntimeError(f"{self.name} boom on call {call_index}")
        result = self._results[call_index] if call_index < len(self._results) else 0
        return result


@pytest.mark.asyncio
async def test_job_calls_each_store_with_its_ttl() -> None:
    a = FakePurgeStore("history")
    a.add_result(3)
    b = FakePurgeStore("signals")
    b.add_result(7)
    job = AgentDataPurgeJob([(a, 90), (b, 30)], interval_seconds=0.05)

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert a.ttl_calls, "history store must be called"
    assert b.ttl_calls, "signal store must be called"
    # Each store always receives ITS OWN ttl (90 vs 30).
    assert set(a.ttl_calls) == {90}
    assert set(b.ttl_calls) == {30}


@pytest.mark.asyncio
async def test_job_handles_store_exception_other_store_continues() -> None:
    a = FakePurgeStore("history")
    a.error_on_call(0)
    b = FakePurgeStore("signals")
    b.add_result(5)
    job = AgentDataPurgeJob([(a, 90), (b, 30)], interval_seconds=0.05)

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    # Failing store did not kill the loop; the healthy store kept running.
    assert 90 in a.ttl_calls, "failing store still attempted (error swallowed)"
    assert b.ttl_calls, "healthy store must keep running after sibling failure"
    assert set(b.ttl_calls) == {30}


@pytest.mark.asyncio
async def test_pre_stopped_job_does_not_run() -> None:
    """Calling stop() before start() should prevent any iteration."""
    a = FakePurgeStore("history")
    job = AgentDataPurgeJob([(a, 90)], interval_seconds=0.05)

    await job.stop()
    await job.start()

    assert a.ttl_calls == []


@pytest.mark.asyncio
async def test_double_start_does_not_run_parallel_loops() -> None:
    """Anti-parallelism guard: a second start() while running is a no-op."""
    a = FakePurgeStore("history")
    # Long interval so the window only captures the first loop's first
    # iteration — any parallel loop from the second start() would add a call.
    job = AgentDataPurgeJob([(a, 90)], interval_seconds=5.0)
    loop_handle = asyncio.ensure_future(job.start())

    await asyncio.sleep(0.02)
    # Second start must not spawn a second purge loop on the same stores.
    await job.start()
    await asyncio.sleep(0.03)
    await job.stop()
    await loop_handle

    # Exactly ONE loop ran: a single first-iteration purge per store.
    assert a.ttl_calls == [90], a.ttl_calls
