"""SqlLearningMetricsRepo pure mappers / shape tests (no live Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime

from diana.infrastructure.db.repositories.learning_metrics import (
    SqlLearningMetricsRepo,
    metric_rows_to_week_dict,
    week_recorded_at,
)


def test_week_recorded_at_is_utc_monday_midnight() -> None:
    ts = week_recorded_at(date(2026, 7, 13))
    assert ts == datetime(2026, 7, 13, 0, 0, 0, tzinfo=UTC)
    assert ts.tzinfo is UTC


def test_metric_rows_to_week_dict_pivots_and_last_wins() -> None:
    rows = [
        ("total_turns", 10.0),
        ("autonomous_send_rate", 0.5),
        ("total_turns", 12.0),
    ]
    out = metric_rows_to_week_dict(rows)
    assert out == {
        "total_turns": 12.0,
        "autonomous_send_rate": 0.5,
    }


def test_repo_accepts_session_factory_and_surface() -> None:
    repo = SqlLearningMetricsRepo(session_factory=object)  # type: ignore[arg-type]
    for name in ("replace_week", "get_week", "get_previous_week", "list_weeks"):
        assert hasattr(repo, name)
        assert inspect.iscoroutinefunction(getattr(repo, name))


def test_exports_in_repositories_package() -> None:
    from diana.infrastructure.db.repositories import SqlLearningMetricsRepo as Exported

    assert Exported is SqlLearningMetricsRepo


def test_metrics_data_trace_mapper_and_window() -> None:
    from uuid import uuid4

    from diana.infrastructure.db.repositories.metrics_data import (
        SqlMetricsDataSource,
        trace_row_to_metrics_dict,
        week_window_utc,
    )

    start, end = week_window_utc(date(2026, 7, 13), date(2026, 7, 20))
    assert start == datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 7, 20, 0, 0, tzinfo=UTC)

    tid = uuid4()
    d = trace_row_to_metrics_dict(
        turn_id=tid,
        decision={"action": "send"},
        timings={"total_ms": 12},
        created_at=start,
    )
    assert d["turn_id"] == tid
    assert d["decision"]["action"] == "send"
    assert d["timings"]["total_ms"] == 12

    src = SqlMetricsDataSource(session_factory=object)  # type: ignore[arg-type]
    for name in (
        "iter_week_traces",
        "corrected_turn_ids",
        "gray_zone_questions",
        "promo_stats",
    ):
        assert hasattr(src, name)
        assert inspect.iscoroutinefunction(getattr(src, name))
