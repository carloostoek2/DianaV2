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

# SPEC-EA-07: severity-graded correction decrement. The "moderate" value equals
# the classic scalar decrement (0.20), so the feature is byte-identical at the
# default severity. Gated by ``severity_decrement_enabled`` (flag
# FEATURE_SEVERITY_TRUST_DECREMENT) — flag OFF → always ``self._decrement``.
DEFAULT_TRUST_BUDGET_DECREMENT_BY_SEVERITY = {
    "minor": 0.08,
    "moderate": 0.20,
    "major": 0.35,
}

# Severity vocabulary of an owner correction (must match the DB CheckConstraint).
_SEVERITY_LEVELS = ("minor", "moderate", "major")

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
        decrement_by_severity: dict[str, float] | None = None,
        severity_decrement_enabled: bool = False,
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
        # SPEC-EA-07: severity-graded deltas (default = fixed table; never
        # auto-calibrated). Constructor args are clamped like the other deltas.
        base = dict(DEFAULT_TRUST_BUDGET_DECREMENT_BY_SEVERITY)
        if decrement_by_severity is not None:
            base.update(decrement_by_severity)
        self._decrement_by_severity: dict[str, float] = {
            str(k): _clamp01(v) for k, v in base.items()
        }
        # Flag governs ONLY the math (regla de oro: OFF → byte-identical).
        self._severity_decrement_enabled = bool(severity_decrement_enabled)
        self._store = store
        self._turn_category_log = turn_category_log
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- manual override (the ONLY mutation point; never auto-calibrated) -----

    def apply_overrides(self, config: dict[str, Any]) -> None:
        """Manual override from ``system_config`` (key ``trust_budget``).

        Missing keys are ignored; invalid values are skipped without crashing
        (pattern ``MoodEngine.apply_overrides``). Never auto-calibrated.

        Range policy (review round 1, S7): unlike ``__init__`` — which CLAMPS
        constructor args to [0, 1] to absorb typos — a manual override silently
        IGNORES any value outside [0, 1]: it is neither applied nor clamped and
        does NOT reject the config. This applies to the scalar keys and to each
        tier of ``decrement_by_severity`` (an out-of-range tier keeps its
        current value).

        All-or-nothing rejection: the WHOLE config is dropped when it would
        invert the conservative asymmetry (``decrement > increment``) or, for the
        severity table, when the effective tiers invert ``minor > increment`` or
        break monotonicity (``major >= moderate >= minor``). The punishment must
        keep outweighing the reward, otherwise the gates stop being conservative
        by design.
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
        # SPEC-EA-07: severity table override — all-or-nothing per tier, like the
        # scalar path. Each provided tier outside [0, 1] is silently IGNORED
        # (neither applied nor clamped, and it does NOT reject the config — the
        # tier keeps its current value). The REAL all-or-nothing rejections: the
        # effective minimum punishment must keep outweighing the reward (minor >
        # increment) and the tiers must be monotone (major >= moderate >= minor).
        # Either violation rejects the WHOLE config.
        severity_candidates: dict[str, float] = {}
        raw_severity = config.get("decrement_by_severity")
        if isinstance(raw_severity, dict):
            for level in _SEVERITY_LEVELS:
                raw_value = raw_severity.get(level)
                if raw_value is None:
                    continue
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if 0.0 <= value <= 1.0:
                    severity_candidates[level] = value
        # The severity table is validated against the EFFECTIVE increment ALWAYS
        # (whether or not the config moves the table). An increment-only override
        # that pushes increment >= minor must be rejected as a whole — otherwise
        # the state would let the minimum punishment (minor) not outweigh the
        # reward, silently inverting conservatism (review round 1, S7).
        effective_severity = dict(self._decrement_by_severity)
        if severity_candidates:
            effective_severity.update(severity_candidates)
        minor = effective_severity["minor"]
        moderate = effective_severity["moderate"]
        major = effective_severity["major"]
        if minor <= increment:
            logger.warning(
                "trust_budget_severity_asymmetry_rejected",
                extra={
                    "minor": minor,
                    "increment": increment,
                    "moderate": moderate,
                    "major": major,
                },
            )
            return
        if not (major >= moderate >= minor):
            logger.warning(
                "trust_budget_severity_asymmetry_rejected",
                extra={
                    "minor": minor,
                    "moderate": moderate,
                    "major": major,
                },
            )
            return
        for key, value in candidates.items():
            setattr(self, f"_{key}", value)
        if severity_candidates:
            self._decrement_by_severity.update(severity_candidates)
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

    def _decrement_for(self, severity: str | None) -> float:
        """Resolved correction decrement (SPEC-EA-07).

        Flag OFF (default) → always ``self._decrement`` — byte-identical to the
        pre-feature behavior regardless of severity. Flag ON → the severity
        table with a fallback to ``self._decrement`` for unknown severities
        (``None`` included, e.g. the reprimand flow). This single switch
        centralizes the regla de oro "flag OFF = byte-idéntico".
        """
        if not self._severity_decrement_enabled:
            return self._decrement
        return self._decrement_by_severity.get(severity, self._decrement)

    def _log_shadow(self, severity: str | None) -> None:
        """Shadow log of the severity-graded delta the feature WOULD apply.

        Only when the flag is OFF and the severity's hypothetical delta differs
        from the applied scalar decrement: the score is untouched (applied_delta
        = self._decrement), but the hypothetical severity delta is logged so the
        distribution is measurable before the flag ships. Channel = module
        logger (robust even with no ledger, e.g. quality OFF).

        KNOWN STATE (SPEC-EA-07, not a new bug): with quality ON + readiness OFF
        (the pre-existing double-counting config) ``trust_severity_shadow`` MAY
        be emitted TWICE for the same turn — camino A (``record_correction`` in
        ``_correct_core``) plus camino B (``record_outcome`` in
        ``record_owner_outcome``). The ledger ``correction_severity`` is
        persisted only ONCE (camino B).
        """
        if self._severity_decrement_enabled:
            return
        hypothetical = self._decrement_by_severity.get(severity)
        if hypothetical is None or hypothetical == self._decrement:
            return
        logger.info(
            "trust_severity_shadow",
            extra={
                "severity": severity,
                "applied_delta": self._decrement,
                "hypothetical_delta": hypothetical,
            },
        )

    async def record_correction(
        self, turn_id: Any, *, severity: str | None = "moderate"
    ) -> VipTrustBudgetRecord | None:
        """Owner-correction event: resolve (VIP, category) by turn_id and decay.

        ``turn_id`` is UNIQUE in ``turn_category_log`` → at most one row. The
        decrement applies ONLY when the corrected turn was an autonomous
        candidate (``would_autonomous == True``): a supervised turn never
        increments, so a correction on it must not seed a 0.0 row with an
        inflated ``correction_count`` (review round 1, S2). A turn without a
        classification (pre-Fase-2) or a non-VIP turn (``vip_id`` None) is also
        a no-op — no row is created without a category (A2).

        SPEC-EA-07: ``severity`` (minor/moderate/major) selects the delta ONLY
        when the severity feature flag is ON; flag OFF → ``self._decrement``
        (byte-identical) with a shadow log of the hypothetical delta.
        """
        log = await self._turn_category_log.get_by_turn_id(turn_id)
        if log is None or log.vip_id is None or not log.would_autonomous:
            return None
        self._log_shadow(severity)
        return await self._store.decrement_correction(
            log.vip_id,
            log.category,
            delta=self._decrement_for(severity),
            initial=self._initial,
            correction_time=self._clock(),
        )

    async def record_outcome(
        self,
        turn_id: Any,
        *,
        event: str,
        value: str,
        severity: str | None = "moderate",
    ) -> VipTrustBudgetRecord | None:
        """Fila 4 outcome-driven trust event (SPEC-AUTONOMIA-CALIBRACION §7).

        When the Fila 4 readiness layer is ON, this is the SINGLE source of
        trust adjustments (the shadow ``record_autonomous`` increment and the
        ``record_correction`` decrement are disabled to avoid double counting).
        Same asymmetric mechanics, event-mapped:

        - ``event="label"`` (C1): ``desacuerdo`` → −decrement (correction);
          ``acierto`` → +increment; ``conservadora`` → no change.
        - ``event="signal"`` (C3): ``negative`` → −decrement;
          ``positive`` → +increment; ``neutral``/``silence`` → no change.

        Resolves (VIP, category) by ``turn_id`` via ``turn_category_log``
        (same reader as ``record_correction``); unclassified / non-VIP turns
        are a no-op. Never auto-calibrated — the deltas are the fixed
        conservative +0.05 / −0.20 pair (severity-graded only behind the flag).

        SPEC-EA-07: ``severity`` selects the decrement delta ONLY when the flag
        is ON; flag OFF → ``self._decrement`` with a shadow log.
        """
        log = await self._turn_category_log.get_by_turn_id(turn_id)
        if log is None or log.vip_id is None:
            return None
        if event == "label":
            if value == "desacuerdo":
                self._log_shadow(severity)
                return await self._store.decrement_correction(
                    log.vip_id,
                    log.category,
                    delta=self._decrement_for(severity),
                    initial=self._initial,
                    correction_time=self._clock(),
                )
            if value == "acierto":
                return await self._store.increment_autonomous(
                    log.vip_id, log.category, delta=self._increment, initial=self._initial
                )
            return None  # conservadora → no change
        if event == "signal":
            if value == "negative":
                self._log_shadow(severity)
                return await self._store.decrement_correction(
                    log.vip_id,
                    log.category,
                    delta=self._decrement_for(severity),
                    initial=self._initial,
                    correction_time=self._clock(),
                )
            if value == "positive":
                return await self._store.increment_autonomous(
                    log.vip_id, log.category, delta=self._increment, initial=self._initial
                )
            return None  # neutral / silence → no change
        return None

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
    "DEFAULT_TRUST_BUDGET_DECREMENT_BY_SEVERITY",
    "DEFAULT_TRUST_BUDGET_INCREMENT",
    "DEFAULT_TRUST_BUDGET_INITIAL",
    "DEFAULT_TRUST_BUDGET_THRESHOLD",
    "DEFAULT_TRUST_DISPERSION_HIGH",
    "DEFAULT_TRUST_TREND_WINDOW_DAYS",
    "TrustBudgetService",
]
