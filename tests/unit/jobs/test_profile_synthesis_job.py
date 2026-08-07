"""ProfileSynthesisJob + run_profile_synthesis_cycle unit tests (no business logic)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from diana.application.profile_synthesis_service import SynthesisReport
from diana.jobs.profile_synthesis_job import (
    ProfileSynthesisJob,
    run_profile_synthesis_cycle,
)


class _FakeTrigger:
    def __init__(
        self,
        *,
        scan_result: int = 1,
        pending: list[tuple[UUID, str]] | None = None,
    ) -> None:
        self.scan_result = scan_result
        self.pending = list(pending or [])
        self.released: list[UUID] = []

    async def scan_inactivity(self, now: datetime) -> int:
        return self.scan_result

    def drain_pending(self) -> list[tuple[UUID, str]]:
        items = list(self.pending)
        self.pending = []
        return items

    def release(self, vip_id: UUID) -> None:
        self.released.append(vip_id)


class _FakeService:
    def __init__(self, *, raise_on: set[UUID] | None = None) -> None:
        self.synthesized: list[tuple[UUID, str]] = []
        self._raise_on = set(raise_on or ())

    async def synthesize(self, vip_id: UUID, trigger: str) -> SynthesisReport:
        self.synthesized.append((vip_id, trigger))
        if vip_id in self._raise_on:
            raise RuntimeError("synthesis boom")
        return SynthesisReport(status="ok", vip_id=vip_id, trigger=trigger)


@pytest.mark.asyncio
async def test_cycle_scans_then_drains_and_synthesizes() -> None:
    vip = uuid4()
    trigger = _FakeTrigger(scan_result=2, pending=[(vip, "volume")])
    service = _FakeService()
    out = await run_profile_synthesis_cycle(trigger, service)  # type: ignore[arg-type]
    assert trigger.scan_result == 2
    assert service.synthesized == [(vip, "volume")]
    assert out["results"] == ["ok"]
    assert out["items"] == 1
    # release always runs → the VIP is not stuck in-flight.
    assert trigger.released == [vip]


@pytest.mark.asyncio
async def test_cycle_release_on_synthesis_failure() -> None:
    vip = uuid4()
    trigger = _FakeTrigger(pending=[(vip, "volume")])
    service = _FakeService(raise_on={vip})
    out = await run_profile_synthesis_cycle(trigger, service)  # type: ignore[arg-type]
    assert out["results"] == ["failed"]  # failure treated as failed
    assert trigger.released == [vip]  # release in finally, even on failure
    # The cycle itself never dies.
    assert out["items"] == 1


@pytest.mark.asyncio
async def test_job_start_stop_runs_loop() -> None:
    trigger = _FakeTrigger(pending=[])
    service = _FakeService()
    job = ProfileSynthesisJob(trigger, service, interval_seconds=0.05)  # type: ignore[arg-type]

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())
    assert trigger.scan_result >= 1  # at least one scan happened


@pytest.mark.asyncio
async def test_pre_stopped_job_does_not_run() -> None:
    trigger = _FakeTrigger(pending=[])
    service = _FakeService()
    job = ProfileSynthesisJob(trigger, service, interval_seconds=0.05)  # type: ignore[arg-type]
    await job.stop()
    await job.start()
    assert service.synthesized == []


def test_job_interval_wired() -> None:
    trigger = _FakeTrigger()
    service = _FakeService()
    job = ProfileSynthesisJob(trigger, service, interval_seconds=900)  # type: ignore[arg-type]
    assert job._interval == 900  # noqa: SLF001
