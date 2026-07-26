"""Process-local swallowed-exception counter (log_swallowed)."""

from __future__ import annotations

import logging

import pytest

from diana.application.observability import (
    get_swallowed_counts,
    log_swallowed,
    reset_swallowed_counts,
)


@pytest.fixture(autouse=True)
def _clear_swallowed() -> None:
    reset_swallowed_counts()
    yield
    reset_swallowed_counts()


def test_log_swallowed_increments_and_logs_exception(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("diana.application.test_obs")
    with caplog.at_level(logging.ERROR, logger="diana.application.test_obs"):
        try:
            raise RuntimeError("boom")
        except Exception:
            log_swallowed(logger, "evt_a", chat_id=1)

    assert get_swallowed_counts()["evt_a"] == 1
    assert any(r.getMessage() == "evt_a" for r in caplog.records)
    assert any(r.exc_info is not None for r in caplog.records if r.getMessage() == "evt_a")


def test_log_swallowed_second_call_same_event() -> None:
    logger = logging.getLogger("diana.application.test_obs")
    try:
        raise RuntimeError("a")
    except Exception:
        log_swallowed(logger, "evt_a")
    try:
        raise RuntimeError("b")
    except Exception:
        log_swallowed(logger, "evt_a")
    assert get_swallowed_counts()["evt_a"] == 2


def test_log_swallowed_separate_events() -> None:
    logger = logging.getLogger("diana.application.test_obs")
    try:
        raise RuntimeError("x")
    except Exception:
        log_swallowed(logger, "evt_a")
    try:
        raise RuntimeError("y")
    except Exception:
        log_swallowed(logger, "evt_b", chat_id=2)
    counts = get_swallowed_counts()
    assert counts["evt_a"] == 1
    assert counts["evt_b"] == 1


def test_reset_swallowed_counts_clears_all() -> None:
    logger = logging.getLogger("diana.application.test_obs")
    try:
        raise RuntimeError("z")
    except Exception:
        log_swallowed(logger, "evt_a")
    assert get_swallowed_counts()["evt_a"] == 1
    reset_swallowed_counts()
    assert get_swallowed_counts() == {}
