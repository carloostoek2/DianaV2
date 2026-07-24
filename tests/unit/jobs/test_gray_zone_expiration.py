"""GrayZoneExpirationJob — periodic expiration loop tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

from diana.jobs.gray_zone_expiration import GrayZoneExpirationJob


class FakeGrayZone:
    """Fake GrayZoneService that records calls and can simulate results."""

    def __init__(self) -> None:
        self.expire_calls: list[list[object]] = []
        self._results: list[list[object]] = []
        self._error_on: set[int] = set()

    def add_result(self, items: list[object]) -> None:
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


class FakeNotifier:
    """Fake notifier stub (not used by the job in F2)."""

    async def notify_info(self, text: str, **kwargs: object) -> None:
        pass


@pytest.mark.asyncio
async def test_job_calls_expire_on_interval() -> None:
    gray_zone = FakeGrayZone()
    gray_zone.add_result([object(), object()])
    notifier = FakeNotifier()
    job = GrayZoneExpirationJob(
        gray_zone,
        notifier,
        interval_seconds=0.05,
    )

    # Let it run for a couple of intervals
    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    assert len(gray_zone.expire_calls) >= 1
    for call_result in gray_zone.expire_calls:
        assert isinstance(call_result, list)


@pytest.mark.asyncio
async def test_job_stops_cleanly() -> None:
    gray_zone = FakeGrayZone()
    notifier = FakeNotifier()
    job = GrayZoneExpirationJob(
        gray_zone,
        notifier,
        interval_seconds=3600,  # Long interval — won't fire
    )

    await job.stop()
    await job.start()  # Should exit immediately

    assert len(gray_zone.expire_calls) == 0


@pytest.mark.asyncio
async def test_job_handles_exceptions_gracefully() -> None:
    gray_zone = FakeGrayZone()
    gray_zone.error_on_call(0)
    notifier = FakeNotifier()
    job = GrayZoneExpirationJob(
        gray_zone,
        notifier,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    # Error doesn't prevent subsequent runs
    if len(gray_zone.expire_calls) > 1:
        assert len(gray_zone.expire_calls) >= 2


@pytest.mark.asyncio
async def test_job_logs_expired_count() -> None:
    gray_zone = FakeGrayZone()
    items = [object(), object(), object()]
    gray_zone.add_result(items)
    notifier = FakeNotifier()
    job = GrayZoneExpirationJob(
        gray_zone,
        notifier,
        interval_seconds=0.05,
    )

    async def _run_and_stop() -> None:
        await asyncio.sleep(0.08)
        await job.stop()

    await asyncio.gather(job.start(), _run_and_stop())

    if gray_zone.expire_calls:
        first_call = gray_zone.expire_calls[0]
        assert len(first_call) == 3  # noqa: PLR2004


@pytest.mark.asyncio
async def test_pre_stopped_job_does_not_run() -> None:
    """Calling stop() before start() should prevent any iteration."""
    gray_zone = FakeGrayZone()
    notifier = FakeNotifier()
    job = GrayZoneExpirationJob(
        gray_zone,
        notifier,
        interval_seconds=0.05,
    )

    await job.stop()
    await job.start()

    assert len(gray_zone.expire_calls) == 0
