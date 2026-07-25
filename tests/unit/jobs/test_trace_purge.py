"""TracePurgeJob — periodic TTL purge loop tests."""

from __future__ import annotations

import asyncio

import pytest

from diana.jobs.trace_purge import TracePurgeJob


class FakeTraceStore:
    """Fake TraceStore that records purge_expired calls."""

    def __init__(self) -> None:
        self.purge_calls: list[int] = []
        self._results: list[int] = []
        self._error_on: set[int] = set()

    def add_result(self, deleted: int) -> None:
        """Register the next result for purge_expired."""
        self._results.append(deleted)

    def error_on_call(self, call_index: int) -> None:
        self._error_on.add(call_index)

    async def purge_expired(self) -> int:
        call_index = len(self.purge_calls)
        self.purge_calls.append(0)
        if call_index in self._error_on:
            msg = f"simulated error on call {call_index}"
            raise RuntimeError(msg)
        result = self._results[call_index] if call_index < len(self._results) else 0
        self.purge_calls[-1] = result
        return result


@pytest.mark.asyncio
async def test_job_calls_purge_on_interval() -> None:
    store = FakeTraceStore()
    store.add_result(5)
    job = TracePurgeJob(store, interval_seconds=0.05)

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert len(store.purge_calls) >= 1
    # At least one call returned 5 deleted rows
    assert any(c == 5 for c in store.purge_calls)


@pytest.mark.asyncio
async def test_job_handles_purge_exceptions_gracefully() -> None:
    store = FakeTraceStore()
    store.add_result(0)
    store.error_on_call(1)  # second call raises
    job = TracePurgeJob(store, interval_seconds=0.05)

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.18)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    # After error, the loop should continue and try again
    assert len(store.purge_calls) >= 2


@pytest.mark.asyncio
async def test_job_runs_noop_purge_when_nothing_to_delete() -> None:
    store = FakeTraceStore()
    store.add_result(0)  # no rows deleted
    job = TracePurgeJob(store, interval_seconds=0.05)

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.1)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert len(store.purge_calls) >= 1
    assert store.purge_calls[0] == 0


@pytest.mark.asyncio
async def test_pre_stopped_job_does_not_run() -> None:
    """Calling stop() before start() should prevent any iteration."""
    store = FakeTraceStore()
    job = TracePurgeJob(store, interval_seconds=0.05)

    await job.stop()
    await job.start()

    assert len(store.purge_calls) == 0


@pytest.mark.asyncio
async def test_multiple_batches_purged_sequentially() -> None:
    """Verify the job handles multiple purge cycles across intervals."""
    store = FakeTraceStore()
    store.add_result(1000)
    store.add_result(500)
    job = TracePurgeJob(store, interval_seconds=0.05)

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.2)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    # Should have at least 2 calls (could be more due to timing)
    assert len(store.purge_calls) >= 2
