"""CalibrationJob + run_calibration_cycle unit tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from diana.jobs.calibration import CalibrationJob, run_calibration_cycle


class FakeCalibrationReport:
    def __init__(self, status: str = "ok") -> None:
        self.status = status


class FakeCalibrationService:
    def __init__(self) -> None:
        self.calibrate_calls: list[int | None] = []
        self.drift_calls: int = 0
        self._order: list[str] = []
        self._calibrate_error = False
        self._drift_error = False
        self._report = FakeCalibrationReport("ok")
        self._drift: dict[str, float] = {"style_drift_score": 0.02}

    def set_calibrate_error(self, value: bool = True) -> None:
        self._calibrate_error = value

    def set_drift_error(self, value: bool = True) -> None:
        self._drift_error = value

    def set_report(self, status: str) -> None:
        self._report = FakeCalibrationReport(status)

    def set_drift(self, drift: dict[str, float]) -> None:
        self._drift = drift

    async def calibrate_thresholds(
        self, window_days: int | None = None
    ) -> FakeCalibrationReport:
        self.calibrate_calls.append(window_days)
        self._order.append("calibrate")
        if self._calibrate_error:
            raise RuntimeError("calibrate boom")
        return self._report

    async def detect_drift(self) -> dict[str, float]:
        self.drift_calls += 1
        self._order.append("detect_drift")
        if self._drift_error:
            raise RuntimeError("drift boom")
        return dict(self._drift)


@pytest.mark.asyncio
async def test_run_calibration_cycle_order_calibrate_then_drift() -> None:
    svc = FakeCalibrationService()
    out = await run_calibration_cycle(svc)  # type: ignore[arg-type]
    assert svc._order == ["calibrate", "detect_drift"]  # noqa: SLF001
    assert out["calibration"] == "ok"
    assert out["drift"] == {"style_drift_score": 0.02}
    assert svc.calibrate_calls == [None]
    assert svc.drift_calls == 1


@pytest.mark.asyncio
async def test_run_calibration_cycle_propagates_status_and_drift() -> None:
    svc = FakeCalibrationService()
    svc.set_report("insufficient_samples")
    svc.set_drift({"style_drift_score": 0.0})
    out = await run_calibration_cycle(svc)  # type: ignore[arg-type]
    assert out["calibration"] == "insufficient_samples"
    assert out["drift"]["style_drift_score"] == 0.0


@pytest.mark.asyncio
async def test_run_calibration_cycle_swallows_calibrate_errors() -> None:
    svc = FakeCalibrationService()
    svc.set_calibrate_error(True)
    out = await run_calibration_cycle(svc)  # type: ignore[arg-type]
    assert out["calibration"] == "error"
    assert out.get("error") == 1
    # drift must not run if calibrate raised before cycle completed
    assert svc.drift_calls == 0


@pytest.mark.asyncio
async def test_run_calibration_cycle_swallows_drift_errors() -> None:
    svc = FakeCalibrationService()
    svc.set_drift_error(True)
    out = await run_calibration_cycle(svc)  # type: ignore[arg-type]
    assert out["calibration"] == "ok"
    assert out["drift"] == {}
    assert out.get("error") == 1


@pytest.mark.asyncio
async def test_job_start_stop_runs_loop() -> None:
    svc = FakeCalibrationService()
    job = CalibrationJob(svc, interval_seconds=0.05)  # type: ignore[arg-type]

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())
    assert len(svc.calibrate_calls) >= 1
    assert svc.drift_calls >= 1


@pytest.mark.asyncio
async def test_job_handles_run_errors_and_continues() -> None:
    svc = FakeCalibrationService()
    svc.set_calibrate_error(True)
    job = CalibrationJob(svc, interval_seconds=0.05)  # type: ignore[arg-type]

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        await job.stop()

    await asyncio.gather(job.start(), _stop_soon())


@pytest.mark.asyncio
async def test_pre_stopped_job_does_not_run() -> None:
    svc = FakeCalibrationService()
    job = CalibrationJob(svc, interval_seconds=0.05)  # type: ignore[arg-type]
    await job.stop()
    await job.start()
    assert svc.calibrate_calls == []
    assert svc.drift_calls == 0
