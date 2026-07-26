"""Source tests: main.py starts/stops HealthServer with polling lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

import diana


@pytest.fixture
def _main_src() -> str:
    root = Path(diana.__file__).resolve().parent
    return (root / "main.py").read_text(encoding="utf-8")


def test_main_imports_health_server(_main_src: str) -> None:
    assert "from diana.telegram.health import HealthServer" in _main_src


def test_main_starts_health_before_polling(_main_src: str) -> None:
    start_idx = _main_src.find("await health.start()")
    poll_idx = _main_src.find("start_polling")
    assert start_idx != -1
    assert poll_idx != -1
    assert start_idx < poll_idx


def test_main_stops_health_in_finally(_main_src: str) -> None:
    assert "await health.stop()" in _main_src
    # stop is in the inner finally around polling
    stop_idx = _main_src.find("await health.stop()")
    poll_idx = _main_src.find("start_polling")
    assert stop_idx != -1 and poll_idx != -1
    assert poll_idx < stop_idx


def test_main_health_uses_settings_bind(_main_src: str) -> None:
    assert "settings.health_host" in _main_src
    assert "settings.health_port" in _main_src
    assert "session_factory=app.session_factory" in _main_src
    assert "bot=app.bot" in _main_src


def test_main_health_bind_soft_fails(_main_src: str) -> None:
    """G2-OPS-1: OSError on health.start is caught; polling still available."""
    assert "except OSError" in _main_src
    assert "health_start_failed" in _main_src
    # Soft-fail try wraps health.start before polling
    soft_idx = _main_src.find("except OSError")
    poll_idx = _main_src.find("start_polling")
    assert soft_idx != -1 and poll_idx != -1
    assert soft_idx < poll_idx


def test_main_outer_finally_cancels_jobs(_main_src: str) -> None:
    """Job cancel runs in outer finally (survives health start failure)."""
    # Outer finally must cancel jobs; structure: try health/poll finally cancel
    assert "_cancel_job(calibration_job" in _main_src
    assert "_cancel_job(expiration_job" in _main_src
    # health_start_failed path must not skip cancel — cancel after last finally
    last_finally = _main_src.rfind("finally:")
    assert last_finally != -1
    outer = _main_src[last_finally:]
    assert "_cancel_job(calibration_job" in outer
    assert "_cancel_job(expiration_job" in outer
