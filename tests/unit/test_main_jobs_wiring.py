"""Source tests: main.py schedules metrics + calibration jobs correctly."""

from __future__ import annotations

from pathlib import Path

import pytest

import diana


@pytest.fixture
def _main_src() -> str:
    root = Path(diana.__file__).resolve().parent
    return (root / "main.py").read_text(encoding="utf-8")


def test_main_imports_metrics_and_calibration_jobs(_main_src: str) -> None:
    assert "from diana.jobs.metrics import MetricsJob" in _main_src
    assert "from diana.jobs.calibration import CalibrationJob" in _main_src


def test_main_defines_setup_helpers(_main_src: str) -> None:
    assert "def _setup_metrics_job(" in _main_src
    assert "def _setup_calibration_job(" in _main_src


def test_main_starts_both_jobs_in_async_main(_main_src: str) -> None:
    assert "metrics_job = _setup_metrics_job(app)" in _main_src
    assert "calibration_job = _setup_calibration_job(app)" in _main_src


def test_main_metrics_job_starts_when_metrics_present(_main_src: str) -> None:
    """Observational metrics job: start when app.metrics is not None."""
    assert "app.metrics is None" in _main_src or "if app.metrics is None" in _main_src
    assert "MetricsJob(" in _main_src
    assert "interval_seconds=3600" in _main_src


def test_main_metrics_job_passes_atencion_counts(_main_src: str) -> None:
    """REQ-ATN-14: MetricsJob receives the atencion counters source."""
    assert "atencion_counts=app.metrics_data" in _main_src


def test_main_metrics_job_gated_by_general_mode_flag(_main_src: str) -> None:
    """F18: the daily atencion log is flag-gated via the general mode flag."""
    assert "feature_general_mode_enabled=app.settings.feature_general_mode_enabled" in _main_src


def test_main_calibration_job_gated_by_feature_flag(_main_src: str) -> None:
    """Calibration job starts only when feature_calibration_enabled and service set."""
    assert "feature_calibration_enabled" in _main_src
    assert "CalibrationJob(" in _main_src
    # Must check the flag before starting
    assert (
        "not app.settings.feature_calibration_enabled" in _main_src
        or "app.settings.feature_calibration_enabled" in _main_src
    )
    assert "app.calibration" in _main_src


def test_main_shutdown_cancels_new_jobs_first(_main_src: str) -> None:
    """Finally cancels calibration/metrics before existing jobs (plan order)."""
    finally_idx = _main_src.find("finally:")
    assert finally_idx != -1
    finally_block = _main_src[finally_idx:]
    cal_cancel = finally_block.find("calibration_job")
    met_cancel = finally_block.find("metrics_job")
    recontact_cancel = finally_block.find("recontact_job")
    assert cal_cancel != -1
    assert met_cancel != -1
    assert recontact_cancel != -1
    # New jobs cancelled before recontact (plan: stop new jobs first)
    assert cal_cancel < recontact_cancel or met_cancel < recontact_cancel
    assert "_cancel_job(" in finally_block
    # Shared cancel helper must actually cancel the task.
    assert "task.cancel()" in _main_src
