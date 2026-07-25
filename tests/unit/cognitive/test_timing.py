"""Unit tests for TimingContext context manager."""

from __future__ import annotations

import time

import pytest

from diana.cognitive.timing import TimingContext


class TestTimingContextBasic:
    """TimingContext measures elapsed wall-clock time correctly."""

    def test_timing_context_basic(self) -> None:
        """Enter, exit, check elapsed_ms >= 0."""
        with TimingContext("test") as tc:
            time.sleep(0.01)  # ~10ms
        assert tc.elapsed_ms >= 10.0

    def test_timing_context_elapsed_is_float(self) -> None:
        """elapsed_ms returns a float."""
        with TimingContext("test") as tc:
            pass
        assert isinstance(tc.elapsed_ms, float)
        assert tc.elapsed_ms >= 0.0

    def test_timing_context_does_not_suppress_exceptions(self) -> None:
        """Exception inside the context must propagate (exit returns None)."""
        with pytest.raises(ValueError, match="boom"):
            with TimingContext("x"):
                msg = "boom"
                raise ValueError(msg)

    def test_timing_context_elapsed_before_exit_raises(self) -> None:
        """Accessing elapsed_ms before exit raises RuntimeError."""
        tc = TimingContext("premature")
        tc.__enter__()
        with pytest.raises(RuntimeError, match="not available"):
            _ = tc.elapsed_ms
        tc.__exit__(None, None, None)

    def test_timing_context_never_entered_raises(self) -> None:
        """elapsed_ms before __enter__ raises RuntimeError."""
        tc = TimingContext("never")
        with pytest.raises(RuntimeError, match="not available"):
            _ = tc.elapsed_ms

    def test_timing_context_exit_returns_none(self) -> None:
        """__exit__ must return None (not True) to avoid suppressing exceptions."""
        tc = TimingContext("must-return-none")
        tc.__enter__()
        result = tc.__exit__(None, None, None)
        assert result is None

    def test_timing_context_reuse_after_exit(self) -> None:
        """Same instance can be reused (elapsed_ms resets on re-entry)."""
        tc = TimingContext("reusable")
        with tc:
            time.sleep(0.01)
        first = tc.elapsed_ms
        with tc:
            time.sleep(0.02)
        second = tc.elapsed_ms
        assert first >= 10.0
        assert second >= 20.0
        assert second > first

    def test_timing_step_name_preserved(self) -> None:
        """Step name should be accessible (for debug)."""
        tc = TimingContext("my_step")
        assert tc._step_name == "my_step"
