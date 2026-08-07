"""TrustBudgetService — per-(VIP, turn_category) confidence budget (Fase 5, shadow).

Implements the SPEC-EVOLUCION-AGENTE v1.2 §5.1 trust-score mechanics (EA-01):

    turno autónomo sin corrección (event hook):  trust_score += incremento_pequeño
    owner corrige (event handle_correct):        trust_score -= decremento_mayor

with ``decrement (0.2) > increment (0.05)`` — the punishment weighs more than
the reward (conservative by design) — and clamp to [0, 1]. The score is updated
ONLY by events, NEVER by LLM calibration (incident lesson). ``apply_overrides``
is the single manual override point via ``system_config`` key ``trust_budget``.

The EA-01 double gate is exposed pure and NOT wired to any real send::
    ``can_autonomous`` evaluates only the first condition (trust >= threshold)
    per category; the second condition (evaluation >= Decider mins) is applied
    by the Decider. ``would_autonomous_with_trust`` is a shadow verdict that
    additionally gates on the §5.2 evaluation dispersion.

Pure application module: imports only ``application.ports`` + ``cognitive.models``
+ stdlib (no chat-framework, no persistence, no LLM).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from diana.application.ports import (
    VipTrustBudgetRecord,
    VipTrustBudgetStore,
    TurnCategoryLogReader,
)
from diana.cognitive.models import (
    EvaluationProfile,
    TurnCategory,
    evaluation_dispersion,
)

logger = logging.getLogger("diana.application")

# Fixed defaults (never auto-calibrated). Manual override only via apply_overrides.
DEFAULT_TRUST_BUDGET_INITIAL = 0.2
DEFAULT_TRUST_BUDGET_INCREMENT = 0.05
DEFAULT_TRUST_BUDGET_DECREMENT = 0.2
DEFAULT_TRUST_BUDGET_THRESHOLD = 0.9
DEFAULT_TRUST_DISPERSION_HIGH = 0.25
DEFAULT_TRUST_TREND_WINDOW_DAYS = 14

_DAY_SECONDS = 86400


def _clamp01(value: float) -> float:
    """Clamp a threshold/delta to the unit interval [0, 1]."""
    return min(1.0, max(0.0, float(value)))


class TrustBudgetService:
    """Pure trust-budget mechanics (math + event orchestration, no DB knowledge).

    ``store`` / ``turn_category_log`` are the ``VipTrustBudgetStore`` /
    ``TurnCategoryLogReader`` protocols (duck-typed; the SQL repos or in-memory
    fakes both satisfy them).
    """

    def __init__(
        self,
        *,
        store: VipTrustBudgetStore,
        turn_category_log: TurnCategoryLogReader,
        clock: Callable[[], datetime] | None = None,
        initial: float = DEFAULT_TRUST_BUDGET_INITIAL,
        increment: float = DEFAULT_TRUST_BUDGET_INCREMENT,
        decrement: float = DEFAULT_TRUST_BUDGET_DECREMENT,
        threshold: float = DEFAULT_TRUST_BUDGET_THRESHOLD,
        thresholds_by_category: dict[str, float] | None = None,
        dispersion_high: float = DEFAULT_TRUST_DISPERSION_HIGH,
        trend_window_days: int = DEFAULT_TRUST_TREND_WINDOW_DAYS,
    ) -> None:
        # Clamp to [0, 1] so typo'd constructor args cannot invert the gates.
        self._initial = _clamp01(initial)
        self._increment = _clamp01(increment)
        self._decrement = _clamp01(decrement)
        self._threshold = _clamp01(threshold)
        self._dispersion_high = _clamp01(dispersion_high)
        self._trend_window_days = max(1, int(trend_window_days))
        self._thresholds_by_category: dict[str, float] = {
            str(cat): _clamp01(value)
            for cat, value in (thresholds_by_category or {}).items()
        }
        self._store = store
        self._turn_category_log = turn_category_log
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- manual override (the ONLY mutation point; never auto-calibrated) -----

    def apply_overrides(self, config: dict[str, Any]) -> None:
        """Manual override from ``system_config`` (key ``trust_budget``).

        Missing keys are ignored; invalid values are rejected without crashing
        (pattern ``MoodEngine.apply_overrides``). Never auto-calibrated.

        Validation policy (review round 1, S7): unlike ``__init__`` — which
        CLAMPS constructor args to [0, 1] to absorb typos — an explicit manual
        override REJECTS out-of-range values (a deliberate override must be
        valid, not silently corrected). It also REJECTS the whole config when it
        would invert the conservative asymmetry (``decrement > increment``): the
        punishment must keep outweighing the reward, otherwise the gates stop
        being conservative by design.
        """
        if not isinstance(config, dict):
            return
        # Collect candidate values first, then validate as a whole.
        candidates: dict[str, float] = {}
        for key in ("initial", "increment", "decrement", "threshold",
                    "dispersion_high"):
            raw = config.get(key)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if 0.0 <= value <= 1.0:
                candidates[key] = value
        increment = candidates.get("increment", self._increment)
        decrement = candidates.get("decrement", self._decrement)
        if decrement <= increment:
            logger.warning(
                "trust_budget_asymmetry_rejected",
                extra={"increment": increment, "decrement": decrement},
            )
            return
        for key, value in candidates.items():
            setattr(self, f"_{key}", value)
        raw_window = config.get("trend_window_days")
        if raw_window is not None:
            try:
                window = int(raw_window)
            except (TypeError, ValueError):
                window = 0
            if window >= 1:
                self._trend_window_days = window
        raw_thresholds = config.get("thresholds")
        if isinstance(raw_thresholds, dict):
            for cat, raw_value in raw_thresholds.items():
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if 0.0 <= value <= 1.0:
                    self._thresholds_by_category[str(cat)] = value

    # -- events ----------------------------------------------------------------

    async def record_autonomous(
        self, vip_id: Any, turn_category: TurnCategory
    ) -> VipTrustBudgetRecord:
        """Autonomous-without-correction event: small increment + counter."""
        return await self._store.increment_autonomous(
            vip_id,
            turn_category,
            delta=self._increment,
            initial=self._initial,
        )

    async def record_correction(
        self, turn_id: Any
    ) -> VipTrustBudgetRecord | None:
        """Owner-correction event: resolve (VIP, category) by turn_id and decay.

        ``turn_id`` is UNIQUE in ``turn_category_log`` → at most one row. The
        decrement applies ONLY when the corrected turn was an autonomous
        candidate (``would_autonomous == True``): a supervised turn never
        increments, so a correction on it must not seed a 0.0 row with an
        inflated ``correction_count`` (review round 1, S2). A turn without a
        classification (pre-Fase-2) or a non-VIP turn (``vip_id`` None) is also
        a no-op — no row is created without a category (A2).
        """
        log = await self._turn_category_log.get_by_turn_id(turn_id)
        if log is None or log.vip_id is None or not log.would_autonomous:
            return None
        return await self._store.decrement_correction(
            log.vip_id,
            log.category,
            delta=self._decrement,
            initial=self._initial,
            correction_time=self._clock(),
        )

    # -- double gate (EA-01, exposed pure, NOT wired to any real send) ---------

    def get_threshold(self, turn_category: TurnCategory) -> float:
        """Trust threshold for the category (per-category override wins)."""
        return self._thresholds_by_category.get(turn_category, self._threshold)

    async def can_autonomous(
        self, vip_id: Any, turn_category: TurnCategory
    ) -> bool:
        """FIRST condition of the EA-01 double gate (trust per category) ONLY.

        No row → False (conservative). The SECOND condition (evaluation >=
        Decider mins) is applied by the Decider in its step 5 — the service
        never imports or consults the Decider (AGENTS.md §2.2/§4.1). Composition
        ``autoenviar = decision.action=="send" AND can_autonomous(...)`` is a
        FUTURE application-layer concern (when Fase 2 leaves shadow).
        """
        record = await self._store.get_by_vip_and_category(vip_id, turn_category)
        if record is None:
            return False
        return record.trust_score >= self.get_threshold(turn_category)

    def dispersion_ok(
        self, evaluation: EvaluationProfile | None,
    ) -> bool:
        """§5.2: high spread across the 7 dims → low confidence → no auto-send.

        Deliberately FAIL-OPEN on ``None`` (a missing profile does not gate —
        nothing to disagree): this is a SHADOW helper, not wired to any send
        today, and the caller decides whether an evaluation is mandatory when
        the real auto-send is composed (Fase 5). The metric is a SPREAD, so a
        uniformly LOW profile (std ≈ 0) passes — that is "coherent", not
        "uniformly bad": the Decider's per-dimension minimums gate that case
        separately (AGENTS.md §4.1), never this dispersion helper (review round
        1).
        """
        if evaluation is None:
            return True
        return evaluation_dispersion(evaluation) < self._dispersion_high

    async def would_autonomous_with_trust(
        self,
        vip_id: Any,
        turn_category: TurnCategory,
        evaluation: EvaluationProfile | None,
    ) -> bool:
        """SHADOW verdict: trust gate AND (no profile OR low dispersion).

        Returns the decision WITHOUT applying it — never wired to a real send
        (Fase 2 still in shadow; the non-phatic auto-send is future Fase 5).
        """
        return await self.can_autonomous(
            vip_id, turn_category
        ) and self.dispersion_ok(evaluation)

    # -- ficha (EA-06) ----------------------------------------------------------

    def trend_for(
        self,
        record: VipTrustBudgetRecord,
        *,
        now: datetime,
        window_days: int | None = None,
    ) -> str:
        """Recent trend of a trust record: "down" | "up" | "flat".

        - "down": a correction landed within the window (last_correction_at
          within ``window_days``) — the owner recently lost trust.
        - "up": autonomous runs WITHOUT a recent correction AND a positive
          score. The record has no ``last_autonomous_at`` column, so recency is
          approximated by the score: a score clamped to 0.0 (corrections
          dominated) is NOT "up" even when ``autonomous_count`` > 0 — a VIP
          with one old autonomous and score 0.0 must not show "▲ up" forever
          (review round 1, S4).
        - "flat": no data to judge, or the score was punished back to 0.

        Robustness (review round 1): ``window_days`` <= 0 clamps to a 1-day
        minimum (never the silent default); a ``last_correction_at`` in the
        future (clock skew) is ignored for the windowed-down check so it cannot
        report "down" forever.
        """
        window = (
            self._trend_window_days
            if window_days is None
            else max(1, int(window_days))
        )
        if record.correction_count > 0 and record.last_correction_at is not None:
            correction = record.last_correction_at
            if correction <= now:
                age_seconds = (now - correction).total_seconds()
                if age_seconds <= window * _DAY_SECONDS:
                    return "down"
        if record.autonomous_count > 0 and record.trust_score > 0.0:
            return "up"
        return "flat"

    async def list_for_ficha(self, vip_id: Any) -> list[dict]:
        """Rows for the 🔐 Confianza section: per-category score + trend + counts."""
        rows = await self._store.list_by_vip(vip_id)
        now = self._clock()
        return [
            {
                "category": record.turn_category,
                "trust_score": record.trust_score,
                "autonomous_count": record.autonomous_count,
                "correction_count": record.correction_count,
                "last_correction_at": (
                    record.last_correction_at.isoformat()
                    if record.last_correction_at is not None
                    else None
                ),
                "trend": self.trend_for(record, now=now),
            }
            for record in rows
        ]


__all__ = [
    "DEFAULT_TRUST_BUDGET_DECREMENT",
    "DEFAULT_TRUST_BUDGET_INCREMENT",
    "DEFAULT_TRUST_BUDGET_INITIAL",
    "DEFAULT_TRUST_BUDGET_THRESHOLD",
    "DEFAULT_TRUST_DISPERSION_HIGH",
    "DEFAULT_TRUST_TREND_WINDOW_DAYS",
    "TrustBudgetService",
]
