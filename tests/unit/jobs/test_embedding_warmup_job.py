"""EmbeddingWarmupJob — warmup in background at boot (hardener/persona-reglas ítem 3, D1)."""

from __future__ import annotations

import asyncio
import logging

import pytest

from diana.jobs.embedding_warmup import DEFAULT_REPAIR_INTERVAL_SECONDS, EmbeddingWarmupJob


class _FakeEmbedder:
    model_name = "fake-mini"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self._fail = fail

    async def warmup(self) -> None:
        self.calls.append("warmup")
        if self._fail:
            raise RuntimeError("no model")


async def _run_then_stop(job: EmbeddingWarmupJob, delay: float = 0.05) -> asyncio.Task:
    task = asyncio.create_task(job.start())
    await asyncio.sleep(delay)
    job.stop()
    await asyncio.wait_for(task, timeout=1.0)
    return task


async def test_start_warms_up_first() -> None:
    emb = _FakeEmbedder()
    job = EmbeddingWarmupJob(emb, interval_seconds=0.01)
    task = await _run_then_stop(job)
    assert task.done()
    assert emb.calls[0] == "warmup"


async def test_warmup_failure_is_logged_and_loop_survives(caplog) -> None:
    emb = _FakeEmbedder(fail=True)
    job = EmbeddingWarmupJob(emb, interval_seconds=0.01)
    with caplog.at_level(logging.INFO, logger="diana.jobs"):
        task = asyncio.create_task(job.start())
        await asyncio.sleep(0.05)
        assert not task.done()  # sigue vivo pese al fallo
        job.stop()
        await asyncio.wait_for(task, timeout=1.0)
    assert any(r.getMessage() == "embedding_warmup_failed" for r in caplog.records)


async def test_stop_ends_loop_promptly() -> None:
    job = EmbeddingWarmupJob(_FakeEmbedder(), interval_seconds=0.01)
    task = asyncio.create_task(job.start())
    await asyncio.sleep(0.02)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    job.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert loop.time() - t0 < 1.0


async def test_no_repair_service_is_noop() -> None:
    job = EmbeddingWarmupJob(_FakeEmbedder(), interval_seconds=0.01)
    assert job._repair is None  # noqa: SLF001
    await job._repair_pass()  # noqa: SLF001  (no lanza)
    assert DEFAULT_REPAIR_INTERVAL_SECONDS == 1800.0


# --- D2: repair pass at boot and periodically ---


class _FakeRepair:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.count = 0

    async def repair_once(self, *, limit: int = 50) -> dict[str, int]:
        self.calls.append("repair")
        self.count += 1
        return {"found": 0, "repaired": 0, "failed": 0}


async def test_repair_runs_right_after_warmup() -> None:
    emb = _FakeEmbedder()
    repair = _FakeRepair(emb.calls)
    job = EmbeddingWarmupJob(emb, repair=repair, interval_seconds=10.0)
    await _run_then_stop(job, delay=0.02)
    assert emb.calls[:2] == ["warmup", "repair"]


async def test_repair_runs_periodically() -> None:
    emb = _FakeEmbedder()
    repair = _FakeRepair([])
    job = EmbeddingWarmupJob(emb, repair=repair, interval_seconds=0.01)
    await _run_then_stop(job, delay=0.1)
    assert repair.count >= 2
