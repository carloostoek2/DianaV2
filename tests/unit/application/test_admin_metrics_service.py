"""AdminMetricsService — owner DM weekly summary formatting (SPEC §7.3)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from diana.application.admin_metrics_service import (
    AdminMetricsService,
    MetricsSummary,
    format_count_delta,
    format_rate_delta,
    format_week_range_label,
)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


class FakeLearningMetricsStore:
    def __init__(self) -> None:
        self.weeks: dict[date, dict[str, float]] = {}

    def seed(self, week_start: date, values: dict[str, float]) -> None:
        self.weeks[week_start] = dict(values)

    async def replace_week(self, week_start: date, values: dict[str, float]) -> None:
        self.weeks[week_start] = dict(values)

    async def get_week(self, week_start: date) -> dict[str, float]:
        return dict(self.weeks.get(week_start, {}))

    async def get_previous_week(self, week_start: date) -> dict[str, float]:
        prev = week_start - timedelta(days=7)
        return dict(self.weeks.get(prev, {}))


def _full_values(**overrides: float) -> dict[str, float]:
    base = {
        "total_turns": 142.0,
        "approval_without_correction_rate": 0.78,
        "gray_zone_repetition_count": 3.0,
        "false_positive_escalation_rate": 0.0,
        "style_drift_score": 0.03,
        "autonomous_send_rate": 0.32,
        "average_latency_ms": 1200.0,
        "promo_sent_count": 12.0,
        "promo_unique_chats": 10.0,
        "promo_repeat_count": 2.0,
    }
    base.update(overrides)
    return base


@pytest.fixture
def store() -> FakeLearningMetricsStore:
    return FakeLearningMetricsStore()


@pytest.fixture
def clock() -> FakeClock:
    # Wednesday 2026-07-29 → previous complete week starts 2026-07-20
    return FakeClock(datetime(2026, 7, 29, 12, 0, tzinfo=UTC))


@pytest.fixture
def svc(store: FakeLearningMetricsStore, clock: FakeClock) -> AdminMetricsService:
    return AdminMetricsService(store=store, clock=clock)


class TestHelpers:
    def test_week_range_label(self) -> None:
        assert format_week_range_label(date(2026, 7, 25), date(2026, 7, 31)) == (
            "25/07",
            "31/07",
        )

    def test_rate_delta_up_percentage_points(self) -> None:
        # 0.78 - 0.73 = 5pp
        assert format_rate_delta(0.78, 0.73) == " (↑ 5% vs semana anterior)"

    def test_rate_delta_down(self) -> None:
        assert format_rate_delta(0.70, 0.75) == " (↓ 5% vs semana anterior)"

    def test_rate_delta_missing_previous(self) -> None:
        assert format_rate_delta(0.78, None) == ""
        assert format_rate_delta(0.78, 0.78) == ""

    def test_count_delta_relative(self) -> None:
        # 2 vs 4 → ↓ 50%
        assert format_count_delta(2.0, 4.0) == " (↓ 50%)"

    def test_count_delta_omit_when_old_zero_or_missing(self) -> None:
        assert format_count_delta(5.0, 0.0) == ""
        assert format_count_delta(5.0, None) == ""


class TestGetWeekSummary:
    async def test_default_week_is_previous_complete(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        store.seed(week, _full_values())
        summary = await svc.get_week_summary()
        assert summary.week_start == week
        assert summary.week_end == date(2026, 7, 26)  # display end = start+6
        assert summary.status == "ok"
        assert summary.values["total_turns"] == 142.0

    async def test_empty_store_status(
        self, svc: AdminMetricsService
    ) -> None:
        summary = await svc.get_week_summary(date(2026, 7, 20))
        assert summary.status == "empty"
        assert summary.values == {}
        assert summary.previous == {}

    async def test_loads_previous_week(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        prev = date(2026, 7, 13)
        store.seed(week, _full_values())
        store.seed(prev, _full_values(approval_without_correction_rate=0.73))
        summary = await svc.get_week_summary(week)
        assert summary.previous["approval_without_correction_rate"] == 0.73


class TestFormatSummaryText:
    async def test_section73_structure_with_deltas(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        prev = date(2026, 7, 13)
        store.seed(week, _full_values())
        store.seed(
            prev,
            _full_values(
                approval_without_correction_rate=0.73,
                false_positive_escalation_rate=0.0,
            ),
        )
        # Seed FP count-like rates for relative delta on derived counts (0)
        summary = await svc.get_week_summary(week)
        text = svc.format_summary_text(summary)

        assert text.startswith(
            "📊 Resumen de aprendizaje (semana del 20/07 al 26/07):"
        )
        assert "- Turnos totales: 142" in text
        assert "- Aprobación sin corrección: 78% (↑ 5% vs semana anterior)" in text
        assert "- Repetición de zona gris: 3" in text
        assert "- Falsos positivos de escalación: 0" in text
        assert "- Drift de estilo: 0.03 (normal)" in text
        assert "- Envíos autónomos: 45 (32% del total)" in text
        assert "- Promos enviadas: 12 (únicos: 10, repetidos: 2)" in text
        # No gray-zone trigger list (Item 2 stores count only)
        assert "mismos triggers" not in text

    async def test_empty_week_friendly_message(
        self, svc: AdminMetricsService
    ) -> None:
        summary = await svc.get_week_summary(date(2026, 7, 20))
        text = svc.format_summary_text(summary)
        assert text == (
            "Sin métricas para la semana del 20/07 al 26/07 "
            "(aún no hay agregación)."
        )

    async def test_drift_label_alto(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        store.seed(week, _full_values(style_drift_score=0.15, total_turns=10.0))
        summary = await svc.get_week_summary(week)
        text = svc.format_summary_text(summary)
        assert "0.15 (alto — revisá las últimas conversaciones)" in text

    async def test_drift_boundary_normal_at_under_0_1(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        store.seed(week, _full_values(style_drift_score=0.099))
        text = svc.format_summary_text(await svc.get_week_summary(week))
        assert "(normal)" in text

    async def test_drift_boundary_alto_at_0_1(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        store.seed(week, _full_values(style_drift_score=0.1))
        text = svc.format_summary_text(await svc.get_week_summary(week))
        assert "alto — revisá" in text

    async def test_no_delta_when_previous_missing(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        store.seed(week, _full_values())
        text = svc.format_summary_text(await svc.get_week_summary(week))
        assert "vs semana anterior" not in text
        assert "↑" not in text and "↓" not in text

    async def test_false_positive_count_with_relative_delta(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        prev = date(2026, 7, 13)
        # Prefer explicit count metric when present
        store.seed(
            week,
            _full_values(
                false_positive_escalation_rate=0.1,
                false_positive_escalation_count=2.0,
            ),
        )
        store.seed(
            prev,
            _full_values(
                false_positive_escalation_rate=0.2,
                false_positive_escalation_count=4.0,
            ),
        )
        text = svc.format_summary_text(await svc.get_week_summary(week))
        assert "- Falsos positivos de escalación: 2 (↓ 50%)" in text


class TestExportWeekJson:
    async def test_export_includes_week_and_values(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        store.seed(week, _full_values())
        raw = await svc.export_week_json(week)
        payload = json.loads(raw)
        assert payload["week_start"] == "2026-07-20"
        assert payload["metrics"]["total_turns"] == 142.0
        assert "status" in payload

    async def test_export_empty_week(
        self, svc: AdminMetricsService
    ) -> None:
        raw = await svc.export_week_json(date(2026, 7, 20))
        payload = json.loads(raw)
        assert payload["status"] == "empty"
        assert payload["metrics"] == {}

    async def test_export_truncates_when_over_telegram_cap(
        self, svc: AdminMetricsService, store: FakeLearningMetricsStore
    ) -> None:
        week = date(2026, 7, 20)
        huge = {f"metric_{i}": float(i) for i in range(500)}
        huge.update(_full_values())
        store.seed(week, huge)
        raw = await svc.export_week_json(week)
        assert len(raw) <= 4096
        assert "truncated" in raw.lower() or raw.endswith("…")


class TestNoAiogram:
    def test_module_importable_without_aiogram(self) -> None:
        import diana.application.admin_metrics_service as mod

        assert hasattr(mod, "AdminMetricsService")
        assert hasattr(mod, "MetricsSummary")
