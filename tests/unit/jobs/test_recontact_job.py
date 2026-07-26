"""RecontactJob + run_due_recontacts unit tests."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from diana.jobs.recontact import RecontactJob, run_due_recontacts


class FakeRecontactService:
    def __init__(self) -> None:
        self.due: list[UUID] = []
        self.execute_calls: list[UUID] = []
        self._results: dict[UUID, str] = {}
        self._errors: set[UUID] = set()
        self._get_due_error = False

    def set_due(self, *vip_ids: UUID) -> None:
        self.due = list(vip_ids)

    def set_result(self, vip_id: UUID, status: str) -> None:
        self._results[vip_id] = status

    def error_on(self, vip_id: UUID) -> None:
        self._errors.add(vip_id)

    async def get_due_vips(self) -> list[UUID]:
        if self._get_due_error:
            raise RuntimeError("get_due boom")
        return list(self.due)

    async def execute_recontact(self, vip_id: UUID) -> str:
        self.execute_calls.append(vip_id)
        if vip_id in self._errors:
            raise RuntimeError(f"execute boom {vip_id}")
        return self._results.get(vip_id, "delivered")


@pytest.mark.asyncio
async def test_run_due_recontacts_executes_each_and_counts() -> None:
    svc = FakeRecontactService()
    a, b = uuid4(), uuid4()
    svc.set_due(a, b)
    svc.set_result(a, "delivered")
    svc.set_result(b, "supervised_skipped")

    counts = await run_due_recontacts(svc)  # type: ignore[arg-type]
    assert svc.execute_calls == [a, b]
    assert counts["delivered"] == 1
    assert counts["supervised_skipped"] == 1
    assert counts["total"] == 2


@pytest.mark.asyncio
async def test_run_due_recontacts_swallows_per_vip_errors() -> None:
    svc = FakeRecontactService()
    a, b = uuid4(), uuid4()
    svc.set_due(a, b)
    svc.error_on(a)
    svc.set_result(b, "delivered")

    counts = await run_due_recontacts(svc)  # type: ignore[arg-type]
    assert b in svc.execute_calls
    assert a in svc.execute_calls
    assert counts["error"] == 1
    assert counts["delivered"] == 1
    assert counts["total"] == 2


@pytest.mark.asyncio
async def test_run_due_recontacts_get_due_error_returns_empty() -> None:
    svc = FakeRecontactService()
    svc._get_due_error = True  # noqa: SLF001
    counts = await run_due_recontacts(svc)  # type: ignore[arg-type]
    assert counts == {"total": 0, "error": 1}
    assert svc.execute_calls == []


@pytest.mark.asyncio
async def test_job_start_stop_runs_due_loop() -> None:
    svc = FakeRecontactService()
    vip = uuid4()
    svc.set_due(vip)
    svc.set_result(vip, "delivered")
    job = RecontactJob(svc, interval_seconds=0.05)  # type: ignore[arg-type]

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())
    assert len(svc.execute_calls) >= 1


@pytest.mark.asyncio
async def test_job_handles_run_errors_and_continues() -> None:
    svc = FakeRecontactService()
    svc._get_due_error = True  # noqa: SLF001
    job = RecontactJob(svc, interval_seconds=0.05)  # type: ignore[arg-type]

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    # Must not raise
    await asyncio.gather(job.start(), _stop_soon())
