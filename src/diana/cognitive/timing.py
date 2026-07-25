"""TimingContext — wall-clock measurement for cognitive pipeline steps.

This module has zero dependencies on application or infrastructure layers.
It never influences control flow — purely measurement.
"""

from __future__ import annotations

import time
from typing import Any


class TimingContext:
    """Context manager that records wall-clock elapsed time for a named step.

    Usage::

        with TimingContext("analyst") as tc:
            comprehension = await analyst.analyze(...)
        timings["analyst_ms"] = tc.elapsed_ms

    ``__exit__`` returns ``None`` — it must NOT suppress exceptions.
    Accessing ``elapsed_ms`` before exit raises ``RuntimeError``.
    """

    def __init__(self, step_name: str) -> None:
        self._step_name = step_name
        self._start: float | None = None
        self._elapsed_ms: float | None = None

    def __enter__(self) -> TimingContext:
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._start is not None:
            elapsed = time.monotonic() - self._start
            self._elapsed_ms = elapsed * 1000.0
        self._start = None
        # Must return None — never suppress exceptions.

    @property
    def step_name(self) -> str:
        """Return the step name this timing context was created for."""
        return self._step_name

    @property
    def elapsed_ms(self) -> float:
        if self._elapsed_ms is None:
            raise RuntimeError(
                f"TimingContext '{self._step_name}': elapsed_ms not available "
                f"yet (context manager may not have exited, or exit never ran)"
            )
        return self._elapsed_ms


__all__ = ["TimingContext"]
