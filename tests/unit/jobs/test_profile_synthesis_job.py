"""ProfileSynthesisJob + run_profile_synthesis_cycle unit tests (no business logic)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from diana.application.ports import VipProfileRecord
from diana.application.profile_synthesis_service import SynthesisReport
from diana.application.profile_synthesis_trigger_service import (
    ProfileSynthesisTriggerService,
)
from diana.jobs.profile_synthesis_job import (
    ProfileSynthesisJob,
    run_profile_synthesis_cycle,
)


class _NoopReader:
    """get_or_create fake returning an empty version-0 default."""

    async def get_or_create(self, vip_id: UUID) -> VipProfileRecord:
        return VipProfileRecord(
            vip_id=vip_id,
            stable_traits={},
            recent_trend={},
            sensitivities=[],
            version=0,
            last_synthesized_at=None,
            synthesis_trigger=None,
        )


class _NoopActivity:
    """Activity fake: no candidates, no message counts."""

    async def count_messages_since(self, vip_id, *, since) -> int:
        return 0

    async def list_vips_with_activity_older_than(self, older_than, *, limit):
        return []


class _FakeTrigger:
    def __init__(
        self,
        *,
        scan_result: int = 1,
        scan_candidates: list[tuple[UUID, str]] | None = None,
        pending: list[tuple[UUID, str]] | None = None,
    ) -> None:
        self.scan_result = scan_result
        self.scan_candidates = list(scan_candidates or [])
        self.pending = list(pending or [])
        self.released: list[UUID] = []

    def enqueue(self, vip_id: UUID, label: str) -> bool:
        """Mirror the real trigger dedup: a VIP is never pending twice."""
        if any(v == vip_id for v, _ in self.pending):
            return False
        self.pending.append((vip_id, label))
        return True

    async def scan_inactivity(self, now: datetime) -> int:
        # The scan feeds pending through the real enqueue link (dedup'd), so
        # the drain of the SAME tick synthesizes exactly what the scan enqueued.
        return sum(1 for vip, label in self.scan_candidates if self.enqueue(vip, label))

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
async def test_cycle_releases_all_drained_on_timeout_b1() -> None:
    """B1: wait_for timeout cancels the cycle mid-loop — EVERY drained VIP is
    released, never leaving an item stuck in ``_in_flight`` across ticks."""
    svc = ProfileSynthesisTriggerService(
        profile_reader=_NoopReader(),
        activity=_NoopActivity(),
        volume_threshold=25,
        inactivity_minutes=30,
    )
    vips = [uuid4() for _ in range(3)]
    for v in vips:
        svc.enqueue(v, "volume")
    # Pending (NOT drained yet — the cycle drains them itself).
    assert len(svc._pending) == 3  # noqa: SLF001

    class _BlockingService:
        async def synthesize(self, vip_id, trigger):
            # Never returns until the cycle is cancelled by the timeout.
            await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            run_profile_synthesis_cycle(svc, _BlockingService()),  # type: ignore[arg-type]
            timeout=0.05,
        )

    # The cleanup finally released EVERY drained VIP — none stuck in-flight.
    assert svc._in_flight == set()  # noqa: SLF001
    # And every VIP is re-enqueueable for the next tick.
    for v in vips:
        assert svc.enqueue(v, "volume") is True


@pytest.mark.asyncio
async def test_cycle_scan_feeds_drain_synthesize_same_tick() -> None:
    """The scan feeds pending via the real enqueue link — the drain of the SAME
    tick synthesizes exactly the VIPs the scan enqueued, end-to-end."""
    vip_a = uuid4()
    vip_b = uuid4()
    trigger = _FakeTrigger(
        scan_candidates=[(vip_a, "volume"), (vip_b, "session_close")],
    )
    service = _FakeService()
    out = await run_profile_synthesis_cycle(trigger, service)  # type: ignore[arg-type]
    assert trigger.pending == []  # the drain emptied exactly what the scan enqueued
    assert service.synthesized == [
        (vip_a, "volume"),
        (vip_b, "session_close"),
    ]  # the VIPs enqueued by the scan are the ones synthesized
    assert out["scanned"] == 2  # the scan returned the count it enqueued
    assert out["items"] == 2
    assert out["results"] == ["ok", "ok"]
    assert sorted(trigger.released) == sorted([vip_a, vip_b])  # both released


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
