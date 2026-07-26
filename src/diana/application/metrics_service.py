"""MetricsAggregationService — weekly learning_metrics aggregation (SPEC §7.1).

Observational only: reads traces/sides, writes EAV metrics. Never mutates
thresholds or runs inside the turn pipeline (AGENTS.md jobs boundary).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("diana.application")

__all__ = [
    "DriftDetector",
    "LearningMetricsStore",
    "METRIC_NAMES",
    "MetricsAggregationService",
    "MetricsSideSource",
    "MetricsTraceSource",
    "WeekMetrics",
    "WeekMetricsReport",
    "previous_complete_week_start",
    "week_bounds",
    "week_metrics_to_eav",
]

METRIC_NAMES: tuple[str, ...] = (
    "total_turns",
    "approval_without_correction_rate",
    "gray_zone_repetition_count",
    "false_positive_escalation_rate",
    "style_drift_score",
    "autonomous_send_rate",
    "average_latency_ms",
    "promo_sent_count",
    "promo_unique_chats",
    "promo_repeat_count",
)

_APPROVE_OR_SEND = frozenset({"approve", "send"})


class DriftDetector(Protocol):
    async def detect_drift(self) -> dict[str, float]: ...


class MetricsTraceSource(Protocol):
    async def iter_week_traces(
        self, week_start: date, week_end: date
    ) -> list[dict]:
        """Each dict: turn_id, decision, timings, created_at, ..."""


class MetricsSideSource(Protocol):
    async def corrected_turn_ids(self, turn_ids: list[UUID]) -> set[UUID]: ...

    async def gray_zone_questions(
        self, week_start: date, week_end: date
    ) -> list[str]: ...

    async def promo_stats(
        self, week_start: date, week_end: date
    ) -> tuple[int, int, int]:
        """sent_count, unique_chats, repeat_count"""


class LearningMetricsStore(Protocol):
    async def replace_week(
        self, week_start: date, values: dict[str, float]
    ) -> None: ...

    async def get_week(self, week_start: date) -> dict[str, float]: ...

    async def get_previous_week(self, week_start: date) -> dict[str, float]: ...


@dataclass(frozen=True)
class WeekMetrics:
    week_start: date
    total_turns: int
    approval_without_correction_rate: float
    gray_zone_repetition_count: int
    false_positive_escalation_rate: float
    style_drift_score: float
    autonomous_send_rate: float
    average_latency_ms: float
    promo_sent_count: int = 0
    promo_unique_chats: int = 0
    promo_repeat_count: int = 0


@dataclass
class WeekMetricsReport:
    status: str  # ok | empty
    metrics: WeekMetrics | None


def week_bounds(week_start: date) -> tuple[date, date]:
    """Return [Monday, next Monday) as dates."""
    return week_start, week_start + timedelta(days=7)


def previous_complete_week_start(now: datetime) -> date:
    """ISO week Monday of the last fully completed week before ``now``."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    today = now.date()
    # Monday of the week containing ``now``
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def week_metrics_to_eav(metrics: WeekMetrics) -> dict[str, float]:
    """Pivot WeekMetrics → EAV metric_name → float (excludes week_start)."""
    raw = asdict(metrics)
    raw.pop("week_start", None)
    return {name: float(raw[name]) for name in METRIC_NAMES}


def _decision_action(trace: dict[str, Any]) -> str | None:
    decision = trace.get("decision")
    if not isinstance(decision, dict):
        return None
    action = decision.get("action")
    return str(action) if action is not None else None


def _trace_turn_id(trace: dict[str, Any]) -> UUID | None:
    raw = trace.get("turn_id")
    if isinstance(raw, UUID):
        return raw
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _latency_ms(timings: object) -> float | None:
    if not isinstance(timings, dict) or not timings:
        return None
    total = timings.get("total_ms")
    if isinstance(total, (int, float)):
        return float(total)
    numeric = [float(v) for v in timings.values() if isinstance(v, (int, float))]
    if not numeric:
        return None
    return float(sum(numeric))


def _gray_zone_repetition_count(questions: list[str]) -> int:
    """Count distinct normalized questions that appear ≥ 2 times."""
    counts: Counter[str] = Counter()
    for q in questions:
        key = str(q).strip().lower()
        if key:
            counts[key] += 1
    return sum(1 for _k, n in counts.items() if n >= 2)


class MetricsAggregationService:
    """Compute SPEC §7.1 weekly fields and persist via LearningMetricsStore."""

    def __init__(
        self,
        *,
        traces: MetricsTraceSource,
        sides: MetricsSideSource,
        store: LearningMetricsStore,
        drift: DriftDetector | None = None,
        clock: Callable[[], datetime] | None = None,
        fp_marks: Any | None = None,
    ) -> None:
        self._traces = traces
        self._sides = sides
        self._store = store
        self._drift = drift
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fp_marks = fp_marks

    def previous_complete_week_start(
        self, now: datetime | None = None
    ) -> date:
        return previous_complete_week_start(now if now is not None else self._clock())

    async def aggregate_week(
        self, week_start: date | None = None
    ) -> WeekMetricsReport:
        if week_start is None:
            week_start = self.previous_complete_week_start()
        start, end = week_bounds(week_start)

        traces = await self._traces.iter_week_traces(start, end)
        total_turns = len(traces)

        turn_ids: list[UUID] = []
        approve_send_ids: list[UUID] = []
        send_count = 0
        escalate_count = 0
        latencies: list[float] = []

        for tr in traces:
            tid = _trace_turn_id(tr)
            action = _decision_action(tr)
            if tid is not None:
                turn_ids.append(tid)
                if action in _APPROVE_OR_SEND:
                    approve_send_ids.append(tid)
            if action == "send":
                send_count += 1
            if action == "escalate":
                escalate_count += 1
            lat = _latency_ms(tr.get("timings"))
            if lat is not None:
                latencies.append(lat)

        corrected: set[UUID] = set()
        if approve_send_ids:
            corrected = await self._sides.corrected_turn_ids(approve_send_ids)

        if approve_send_ids:
            without = sum(1 for t in approve_send_ids if t not in corrected)
            approval_rate = without / len(approve_send_ids)
        else:
            approval_rate = 0.0

        gray_qs = await self._sides.gray_zone_questions(start, end)
        gray_rep = _gray_zone_repetition_count(gray_qs)

        fp_count = 0
        if self._fp_marks is not None:
            try:
                fp_count = int(
                    await self._fp_marks.count_in_range(start, end)
                )
            except Exception:
                logger.exception("metrics_fp_count_failed")
                fp_count = 0
        fp_rate = (fp_count / escalate_count) if escalate_count else 0.0

        style_score = await self._style_drift_score()

        auto_rate = (send_count / total_turns) if total_turns else 0.0
        avg_latency = (
            sum(latencies) / len(latencies) if latencies else 0.0
        )

        promo_sent, promo_unique, promo_repeat = await self._sides.promo_stats(
            start, end
        )

        metrics = WeekMetrics(
            week_start=week_start,
            total_turns=total_turns,
            approval_without_correction_rate=float(approval_rate),
            gray_zone_repetition_count=int(gray_rep),
            false_positive_escalation_rate=fp_rate,
            style_drift_score=float(style_score),
            autonomous_send_rate=float(auto_rate),
            average_latency_ms=float(avg_latency),
            promo_sent_count=int(promo_sent),
            promo_unique_chats=int(promo_unique),
            promo_repeat_count=int(promo_repeat),
        )
        values = week_metrics_to_eav(metrics)
        await self._store.replace_week(week_start, values)

        status = "empty" if total_turns == 0 else "ok"
        logger.info(
            "metrics_aggregate_complete",
            extra={
                "week_start": week_start.isoformat(),
                "status": status,
                "total_turns": total_turns,
            },
        )
        return WeekMetricsReport(status=status, metrics=metrics)

    async def _style_drift_score(self) -> float:
        if self._drift is None:
            return 0.0
        try:
            result = await self._drift.detect_drift()
        except Exception:
            logger.exception("metrics_drift_detector_failed")
            return 0.0
        if not isinstance(result, dict):
            return 0.0
        raw = result.get("style_drift_score", 0.0)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
