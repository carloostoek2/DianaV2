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
