"""MetricsAggregationService unit tests — fakes only (no DB / no pipeline)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from diana.application.metrics_service import (
    MetricsAggregationService,
    WeekMetrics,
    WeekMetricsReport,
    previous_complete_week_start,
    week_bounds,
)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


class FakeTraceSource:
    def __init__(self, traces: list[dict[str, Any]] | None = None) -> None:
        self.traces = list(traces or [])
        self.calls: list[tuple[date, date]] = []

    async def iter_week_traces(
        self, week_start: date, week_end: date
    ) -> list[dict[str, Any]]:
        self.calls.append((week_start, week_end))
        return list(self.traces)


class FakeSideSource:
    def __init__(
        self,
        *,
        corrected: set[UUID] | None = None,
        gray_questions: list[str] | None = None,
        promo: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        self.corrected = set(corrected or ())
        self.gray_questions = list(gray_questions or [])
        self.promo = promo
        self.corrected_calls: list[list[UUID]] = []
        self.gray_calls: list[tuple[date, date]] = []
        self.promo_calls: list[tuple[date, date]] = []

    async def corrected_turn_ids(self, turn_ids: list[UUID]) -> set[UUID]:
        self.corrected_calls.append(list(turn_ids))
        return {t for t in turn_ids if t in self.corrected}

    async def gray_zone_questions(
        self, week_start: date, week_end: date
    ) -> list[str]:
        self.gray_calls.append((week_start, week_end))
        return list(self.gray_questions)

    async def promo_stats(
        self, week_start: date, week_end: date
    ) -> tuple[int, int, int]:
        self.promo_calls.append((week_start, week_end))
        return self.promo


class FakeStore:
    def __init__(self) -> None:
        self.weeks: dict[date, dict[str, float]] = {}
        self.replace_calls: list[tuple[date, dict[str, float]]] = []

    async def replace_week(self, week_start: date, values: dict[str, float]) -> None:
        self.replace_calls.append((week_start, dict(values)))
        self.weeks[week_start] = dict(values)

    async def get_week(self, week_start: date) -> dict[str, float]:
        return dict(self.weeks.get(week_start, {}))

    async def get_previous_week(self, week_start: date) -> dict[str, float]:
        prev = week_start - timedelta(days=7)
        return dict(self.weeks.get(prev, {}))


class FakeDrift:
    def __init__(
        self,
        result: dict[str, float] | None = None,
        *,
        error: bool = False,
    ) -> None:
        self.result = dict(result or {})
        self.error = error
        self.calls = 0

    async def detect_drift(self) -> dict[str, float]:
        self.calls += 1
        if self.error:
            raise RuntimeError("drift boom")
        return dict(self.result)


_TIMINGS_DEFAULT: object = object()


def _trace(
    *,
    action: str,
    turn_id: UUID | None = None,
    timings: Any = _TIMINGS_DEFAULT,
) -> dict[str, Any]:
    if timings is _TIMINGS_DEFAULT:
        resolved_timings: dict[str, Any] | None = {"total_ms": 100.0}
    else:
        resolved_timings = timings
    return {
        "turn_id": turn_id or uuid4(),
        "decision": {"action": action},
        "timings": resolved_timings,
        "created_at": datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    }


# ---------------------------------------------------------------------------
# Pure week helpers
# ---------------------------------------------------------------------------


def test_week_bounds_monday_to_next_monday() -> None:
    start, end = week_bounds(date(2026, 7, 13))  # Monday
    assert start == date(2026, 7, 13)
    assert end == date(2026, 7, 20)


def test_previous_complete_week_start_before_and_after_monday() -> None:
    # Wednesday 2026-07-22 → previous complete week starts Monday 2026-07-13
    wed = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    assert previous_complete_week_start(wed) == date(2026, 7, 13)

    # Monday 2026-07-20 02:00 → previous complete week is 2026-07-13
    mon_early = datetime(2026, 7, 20, 2, 0, tzinfo=UTC)
    assert previous_complete_week_start(mon_early) == date(2026, 7, 13)

    # Monday 2026-07-20 12:00 → still previous complete is 2026-07-13
    # (current week started today; complete previous is last week)
    mon_noon = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    assert previous_complete_week_start(mon_noon) == date(2026, 7, 13)


# ---------------------------------------------------------------------------
# Aggregation fields (SPEC §7.1 / A4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_empty_week_writes_zeros() -> None:
    store = FakeStore()
    svc = MetricsAggregationService(
        traces=FakeTraceSource([]),
        sides=FakeSideSource(),
        store=store,
        clock=FakeClock(datetime(2026, 7, 22, 12, 0, tzinfo=UTC)),
    )
    report = await svc.aggregate_week(date(2026, 7, 13))
    assert report.status == "empty"
    assert report.metrics is not None
    m = report.metrics
    assert m.week_start == date(2026, 7, 13)
    assert m.total_turns == 0
    assert m.approval_without_correction_rate == 0.0
    assert m.gray_zone_repetition_count == 0
    assert m.false_positive_escalation_rate == 0.0
    assert m.style_drift_score == 0.0
    assert m.autonomous_send_rate == 0.0
    assert m.average_latency_ms == 0.0
    assert m.promo_sent_count == 0
    assert store.replace_calls
    values = store.replace_calls[0][1]
    assert values["total_turns"] == 0.0
    assert values["false_positive_escalation_rate"] == 0.0


@pytest.mark.asyncio
async def test_aggregate_computes_all_section_71_fields() -> None:
    t_approve = uuid4()
    t_send = uuid4()
    t_escalate = uuid4()
    t_corrected = uuid4()

    traces = [
        _trace(action="approve", turn_id=t_approve, timings={"total_ms": 100}),
        _trace(action="send", turn_id=t_send, timings={"total_ms": 200}),
        _trace(action="escalate", turn_id=t_escalate, timings={"total_ms": 50}),
        _trace(action="approve", turn_id=t_corrected, timings={"total_ms": 150}),
    ]
    store = FakeStore()
    drift = FakeDrift({"style_drift_score": 0.42})
    sides = FakeSideSource(
        corrected={t_corrected},
        gray_questions=["  Price? ", "price?", "Shipping", "shipping", "Other"],
        promo=(5, 3, 2),
    )
    svc = MetricsAggregationService(
        traces=FakeTraceSource(traces),
        sides=sides,
        store=store,
        drift=drift,
        clock=FakeClock(datetime(2026, 7, 22, 12, 0, tzinfo=UTC)),
    )
    report = await svc.aggregate_week(date(2026, 7, 13))
    assert report.status == "ok"
    assert isinstance(report.metrics, WeekMetrics)
    m = report.metrics
    assert m.total_turns == 4
    # approve/send without correction: approve (ok), send (ok), approve corrected (no)
    # denominator = 3 (approve, send, approve_corrected); numerator = 2
    assert m.approval_without_correction_rate == pytest.approx(2 / 3)
    # repeated questions after normalize: "price?" x2, "shipping" x2 → 2 groups
    assert m.gray_zone_repetition_count == 2
    assert m.false_positive_escalation_rate == 0.0
    assert m.style_drift_score == pytest.approx(0.42)
    assert m.autonomous_send_rate == pytest.approx(1 / 4)
    assert m.average_latency_ms == pytest.approx((100 + 200 + 50 + 150) / 4)
    assert m.promo_sent_count == 5
    assert m.promo_unique_chats == 3
    assert m.promo_repeat_count == 2

    values = store.weeks[date(2026, 7, 13)]
    for key in (
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
    ):
        assert key in values
    assert 0.0 <= values["approval_without_correction_rate"] <= 1.0
    assert 0.0 <= values["autonomous_send_rate"] <= 1.0
    assert values["gray_zone_repetition_count"] >= 0
    assert drift.calls == 1


@pytest.mark.asyncio
async def test_average_latency_falls_back_to_sum_of_numeric_timings() -> None:
    traces = [
        _trace(action="approve", timings={"a_ms": 10, "b_ms": 20}),
        _trace(action="send", timings={"total_ms": 40}),
        _trace(action="approve", timings=None),
        _trace(action="send", timings={"x": "not-a-number"}),
    ]
    store = FakeStore()
    svc = MetricsAggregationService(
        traces=FakeTraceSource(traces),
        sides=FakeSideSource(),
        store=store,
    )
    report = await svc.aggregate_week(date(2026, 7, 13))
    assert report.metrics is not None
    # only first two contribute: 30 and 40 → mean 35
    assert report.metrics.average_latency_ms == pytest.approx(35.0)


@pytest.mark.asyncio
async def test_drift_none_or_error_yields_zero() -> None:
    traces = [_trace(action="send")]
    store = FakeStore()
    svc_none = MetricsAggregationService(
        traces=FakeTraceSource(traces),
        sides=FakeSideSource(),
        store=store,
        drift=None,
    )
    r1 = await svc_none.aggregate_week(date(2026, 7, 13))
    assert r1.metrics is not None
    assert r1.metrics.style_drift_score == 0.0

    store2 = FakeStore()
    svc_err = MetricsAggregationService(
        traces=FakeTraceSource(traces),
        sides=FakeSideSource(),
        store=store2,
        drift=FakeDrift(error=True),
    )
    r2 = await svc_err.aggregate_week(date(2026, 7, 13))
    assert r2.metrics is not None
    assert r2.metrics.style_drift_score == 0.0


@pytest.mark.asyncio
async def test_idempotent_replace_overwrites_week() -> None:
    store = FakeStore()
    traces1 = [_trace(action="send"), _trace(action="approve")]
    svc = MetricsAggregationService(
        traces=FakeTraceSource(traces1),
        sides=FakeSideSource(promo=(1, 1, 0)),
        store=store,
        drift=FakeDrift({"style_drift_score": 0.1}),
    )
    await svc.aggregate_week(date(2026, 7, 13))
    assert store.weeks[date(2026, 7, 13)]["total_turns"] == 2.0

    svc2 = MetricsAggregationService(
        traces=FakeTraceSource([_trace(action="escalate")]),
        sides=FakeSideSource(promo=(9, 2, 7)),
        store=store,
        drift=FakeDrift({"style_drift_score": 0.9}),
    )
    await svc2.aggregate_week(date(2026, 7, 13))
    assert len(store.replace_calls) == 2
    assert store.weeks[date(2026, 7, 13)]["total_turns"] == 1.0
    assert store.weeks[date(2026, 7, 13)]["style_drift_score"] == pytest.approx(0.9)
    assert store.weeks[date(2026, 7, 13)]["promo_sent_count"] == 9.0


@pytest.mark.asyncio
async def test_default_week_is_previous_complete_iso_week() -> None:
    store = FakeStore()
    traces_src = FakeTraceSource([])
    clock = FakeClock(datetime(2026, 7, 22, 15, 0, tzinfo=UTC))  # Wed
    svc = MetricsAggregationService(
        traces=traces_src,
        sides=FakeSideSource(),
        store=store,
        clock=clock,
    )
    report = await svc.aggregate_week(None)
    assert report.metrics is not None
    assert report.metrics.week_start == date(2026, 7, 13)
    assert traces_src.calls == [(date(2026, 7, 13), date(2026, 7, 20))]


@pytest.mark.asyncio
async def test_approval_rate_zero_when_no_approve_or_send() -> None:
    traces = [_trace(action="escalate"), _trace(action="consult_doctrine")]
    store = FakeStore()
    svc = MetricsAggregationService(
        traces=FakeTraceSource(traces),
        sides=FakeSideSource(),
        store=store,
    )
    report = await svc.aggregate_week(date(2026, 7, 13))
    assert report.metrics is not None
    assert report.metrics.approval_without_correction_rate == 0.0
    assert report.metrics.total_turns == 2


@pytest.mark.asyncio
async def test_previous_complete_week_start_method_uses_clock() -> None:
    clock = FakeClock(datetime(2026, 7, 22, 12, 0, tzinfo=UTC))
    svc = MetricsAggregationService(
        traces=FakeTraceSource(),
        sides=FakeSideSource(),
        store=FakeStore(),
        clock=clock,
    )
    assert svc.previous_complete_week_start() == date(2026, 7, 13)
    assert svc.previous_complete_week_start(
        datetime(2026, 7, 27, 0, 0, tzinfo=UTC)
    ) == date(2026, 7, 20)


@pytest.mark.asyncio
async def test_report_type_and_rates_in_unit_interval() -> None:
    store = FakeStore()
    svc = MetricsAggregationService(
        traces=FakeTraceSource(
            [
                _trace(action="send"),
                _trace(action="send"),
                _trace(action="approve"),
            ]
        ),
        sides=FakeSideSource(),
        store=store,
    )
    report = await svc.aggregate_week(date(2026, 7, 13))
    assert isinstance(report, WeekMetricsReport)
    assert report.metrics is not None
    assert 0.0 <= report.metrics.autonomous_send_rate <= 1.0
    assert 0.0 <= report.metrics.approval_without_correction_rate <= 1.0
    assert report.metrics.false_positive_escalation_rate == 0.0



@pytest.mark.asyncio
async def test_false_positive_rate_from_owner_marks() -> None:
    """R5: fp_rate = fp_count / escalate_count when owner marks exist."""
    from diana.application.owner_marks import InMemoryOwnerMarkStore

    t_esc1 = uuid4()
    t_esc2 = uuid4()
    t_ok = uuid4()
    traces = [
        _trace(action="escalate", turn_id=t_esc1),
        _trace(action="escalate", turn_id=t_esc2),
        _trace(action="approve", turn_id=t_ok),
    ]
    marks = InMemoryOwnerMarkStore()
    # mark one escalate as FP inside week
    marks._clock = lambda: datetime(2026, 7, 14, 10, 0, tzinfo=UTC)  # noqa: SLF001
    await marks.mark(t_esc1)

    store = FakeStore()
    svc = MetricsAggregationService(
        traces=FakeTraceSource(traces),
        sides=FakeSideSource(),
        store=store,
        fp_marks=marks,
        clock=FakeClock(datetime(2026, 7, 22, 12, 0, tzinfo=UTC)),
    )
    report = await svc.aggregate_week(date(2026, 7, 13))
    assert report.metrics is not None
    # 1 FP / 2 escalates
    assert report.metrics.false_positive_escalation_rate == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_false_positive_rate_zero_when_no_escalations() -> None:
    from diana.application.owner_marks import InMemoryOwnerMarkStore

    marks = InMemoryOwnerMarkStore()
    marks._clock = lambda: datetime(2026, 7, 14, tzinfo=UTC)  # noqa: SLF001
    await marks.mark(uuid4())
    svc = MetricsAggregationService(
        traces=FakeTraceSource([_trace(action="approve")]),
        sides=FakeSideSource(),
        store=FakeStore(),
        fp_marks=marks,
        clock=FakeClock(datetime(2026, 7, 22, 12, 0, tzinfo=UTC)),
    )
    report = await svc.aggregate_week(date(2026, 7, 13))
    assert report.metrics is not None
    assert report.metrics.false_positive_escalation_rate == 0.0
