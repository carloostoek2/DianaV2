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
    finally_idx = _main_src.find("finally:")
    assert finally_idx != -1
    finally_block = _main_src[finally_idx:]
    assert "await health.stop()" in finally_block


def test_main_health_uses_settings_bind(_main_src: str) -> None:
    assert "settings.health_host" in _main_src
    assert "settings.health_port" in _main_src
    assert "session_factory=app.session_factory" in _main_src
    assert "bot=app.bot" in _main_src
