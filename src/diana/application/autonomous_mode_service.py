"""AutonomousModeService — L2 enablement gate + near-threshold owner notify.

L1: settings.feature_autonomous_mode (master kill-switch).
L2: L1 AND (global_mode == "autonomous" OR vip.auto_send).
L3: Decider thresholds → action "send" (consumed by TurnOrchestrator).

Does not re-decide evaluation dims, call LLMs, or deliver messages.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from uuid import UUID

from diana.application.ports import OwnerNotifierPort, VipStore
from diana.cognitive.models import Decision, EvaluationProfile
from diana.cognitive.thresholds import DEFAULT_AUTONOMOUS_THRESHOLDS

logger = logging.getLogger("diana.application")

_NEAR_DIMS: tuple[tuple[str, str], ...] = (
    ("safety", "safety_min"),
    ("doctrine", "doctrine_min"),
    ("naturalness", "naturalness_min"),
)


class AutonomousModeService:
    """L2 gate for autonomous VIP auto-send + operational near-threshold notify."""

    def __init__(
        self,
        *,
        feature_autonomous_mode: bool,
        global_mode: str,
        vip_store: VipStore,
        notifier: OwnerNotifierPort,
        autonomous_thresholds: Mapping[str, float] | None = None,
        near_margin: float = 0.05,
    ) -> None:
        self._feature_autonomous_mode = feature_autonomous_mode
        self._global_mode = global_mode
        self._vip_store = vip_store
        self._notifier = notifier
        mins = dict(DEFAULT_AUTONOMOUS_THRESHOLDS)
        if autonomous_thresholds:
            mins.update(autonomous_thresholds)
        self._mins = mins
        self._near_margin = near_margin

    async def is_autonomous_enabled(self, vip_id: UUID | None = None) -> bool:
        """Return True iff L1 is on and global autonomous OR vip.auto_send."""
        if not self._feature_autonomous_mode:
            return False
        if self._global_mode == "autonomous":
            return True
        if vip_id is None:
            return False
        vip = await self._vip_store.get_by_id(vip_id)
        if vip is None:
            return False
        return bool(getattr(vip, "auto_send", False))

    async def notify_if_needed(
        self,
        turn_id: UUID,
        decision: Decision,
        evaluation: EvaluationProfile,
    ) -> None:
        """Owner operational notify if any dim is in [min, min+margin).

        Never raises — notifier failures are logged only.
        """
        near: list[str] = []
        for attr, min_key in _NEAR_DIMS:
            value = float(getattr(evaluation, attr))
            lo = float(self._mins[min_key])
            hi = lo + self._near_margin
            if lo <= value < hi:
                near.append(f"{attr}={value:.2f} (min={lo:.2f})")

        if not near:
            return

        text = (
            f"Turn {turn_id} autonomous send near threshold: "
            + ", ".join(near)
            + f" (reason={decision.reason})"
        )
        try:
            await self._notifier.notify_info(text)
        except Exception:
            logger.exception(
                "autonomous_near_threshold_notify_failed",
                extra={"turn_id": str(turn_id)},
            )


__all__ = ["AutonomousModeService"]
