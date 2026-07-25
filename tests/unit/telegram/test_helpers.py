"""Unit tests for telegram.helpers shared presentation helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from diana.telegram.helpers import _format_relative_time


class TestFormatRelativeTime:
    """Exhaustive branch coverage for _format_relative_time."""

    def test_none_returns_empty_string(self) -> None:
        assert _format_relative_time(None) == ""

    def test_future_date_returns_formatted(self) -> None:
        dt = datetime.now(UTC) + timedelta(hours=1)
        assert _format_relative_time(dt) == dt.strftime("%d/%m/%Y")

    def test_less_than_one_minute(self) -> None:
        dt = datetime.now(UTC) - timedelta(seconds=30)
        assert _format_relative_time(dt) == "hace menos de un minuto"

    def test_exactly_one_minute(self) -> None:
        dt = datetime.now(UTC) - timedelta(minutes=1)
        assert _format_relative_time(dt) == "hace 1 minuto"

    def test_multiple_minutes(self) -> None:
        dt = datetime.now(UTC) - timedelta(minutes=5)
        assert _format_relative_time(dt) == "hace 5 minutos"

    def test_exactly_one_hour(self) -> None:
        dt = datetime.now(UTC) - timedelta(hours=1)
        assert _format_relative_time(dt) == "hace 1 hora"

    def test_multiple_hours(self) -> None:
        dt = datetime.now(UTC) - timedelta(hours=3)
        assert _format_relative_time(dt) == "hace 3 horas"

    def test_yesterday_same_hour_format(self) -> None:
        """'about 24 hours ago' should return 'ayer a las HH:MM'."""
        dt = datetime.now(UTC) - timedelta(hours=24)
        result = _format_relative_time(dt)
        expected_time = dt.strftime("%H:%M")
        assert result == f"ayer a las {expected_time}"

    def test_two_days(self) -> None:
        dt = datetime.now(UTC) - timedelta(days=2)
        assert _format_relative_time(dt) == "hace 2 días"

    def test_six_days(self) -> None:
        dt = datetime.now(UTC) - timedelta(days=6)
        assert _format_relative_time(dt) == "hace 6 días"

    def test_seven_plus_days_returns_date_format(self) -> None:
        dt = datetime.now(UTC) - timedelta(days=7)
        assert _format_relative_time(dt) == dt.strftime("%d/%m/%Y")

    def test_thirty_days_returns_date_format(self) -> None:
        dt = datetime.now(UTC) - timedelta(days=30)
        assert _format_relative_time(dt) == dt.strftime("%d/%m/%Y")

    def test_naive_datetime_treated_as_utc(self) -> None:
        """A datetime without tzinfo should be treated as UTC."""
        dt = datetime.now(UTC) - timedelta(minutes=5)
        naive = dt.replace(tzinfo=None)
        result = _format_relative_time(naive)
        assert result == "hace 5 minutos"

    def test_seconds_exactly_zero_is_less_than_one_minute(self) -> None:
        """0 delta should return 'hace menos de un minuto'."""
        dt = datetime.now(UTC) - timedelta(seconds=0)
        assert _format_relative_time(dt) == "hace menos de un minuto"

    def test_almost_one_day_returns_hours(self) -> None:
        """23:59 hours should still be 'hace X horas', not 'ayer'."""
        dt = datetime.now(UTC) - timedelta(hours=23, minutes=59)
        result = _format_relative_time(dt)
        assert "hace" in result
        assert "hora" in result
        assert result == "hace 23 horas"
