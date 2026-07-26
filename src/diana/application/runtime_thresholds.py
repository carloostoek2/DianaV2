"""Shared mutable evaluation thresholds for live Decider reads after calibration.

Composition builds one instance; CalibrationService.replace_autonomous after
DB write; Decider reads mins inside decide() so process restart is not required.
"""

from __future__ import annotations

from collections.abc import Mapping

from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS

__all__ = ["RuntimeThresholds"]

_DEFAULT_SAFETY = 0.3


class RuntimeThresholds:
    """In-process holder for autonomous mins (+ optional P1 safety)."""

    def __init__(
        self,
        autonomous: Mapping[str, float] | None = None,
        safety: float = _DEFAULT_SAFETY,
    ) -> None:
        self._safety = float(safety)
        self._autonomous = self._merge_autonomous(autonomous)

    @staticmethod
    def _merge_autonomous(
        values: Mapping[str, float] | None,
    ) -> dict[str, float]:
        mins = {k: float(v) for k, v in DEFAULT_AUTONOMOUS_THRESHOLDS.items()}
        if values is not None:
            for key, val in values.items():
                mins[str(key)] = float(val)
        return mins

    @property
    def autonomous(self) -> Mapping[str, float]:
        return dict(self._autonomous)

    @property
    def safety(self) -> float:
        return self._safety

    def replace_autonomous(self, values: Mapping[str, float]) -> None:
        self._autonomous = self._merge_autonomous(values)

    def replace_safety(self, value: float) -> None:
        self._safety = float(value)
