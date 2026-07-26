"""Metrics dashboard keyboard + callback dispatch (mx:e / mx:b)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from diana.application.admin_metrics_service import AdminMetricsService
from diana.application.admin_service import AdminService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
)
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.telegram.handlers.callbacks import (
    ADMIN_MENU_TEXT,
    CorrectSessionStore,
    dispatch_owner_callback,
)
from diana.telegram.keyboards import (
    encode_metrics_back,
    encode_metrics_export,
    metrics_keyboard,
    parse_metrics_callback,
)

OWNER = 999001
OTHER = 111


class _FakeMetricsStore:
    def __init__(self) -> None:
        self.weeks: dict[date, dict[str, float]] = {}

    def seed(self, week_start: date, values: dict[str, float]) -> None:
        self.weeks[week_start] = dict(values)

    async def replace_week(self, week_start: date, values: dict[str, float]) -> None:
        self.weeks[week_start] = dict(values)

    async def get_week(self, week_start: date) -> dict[str, float]:
        return dict(self.weeks.get(week_start, {}))

    async def get_previous_week(self, week_start: date) -> dict[str, float]:
        return dict(self.weeks.get(week_start - timedelta(days=7), {}))


@pytest.fixture
def admin() -> AdminService:
    deliveries = InMemoryPendingDeliveryStore()
    behavior = BehaviorEngine(
        FakeTelegramActuator(),
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    turns = InMemoryTurnStore()
    coordinator = TurnCoordinator(turns, InMemoryPendingApprovalStore(), behavior)
    return AdminService(
        notifier=FakeOwnerNotifier(),
        approvals=InMemoryPendingApprovalStore(),
        escalations=InMemoryEscalationStore(),
        coordinator=coordinator,
        behavior=behavior,
        traces=InMemoryTraceReaderWriter(),
        turns=turns,
        owner_telegram_id=OWNER,
    )


@pytest.fixture
def admin_metrics() -> AdminMetricsService:
    store = _FakeMetricsStore()
    store.seed(
        date(2026, 7, 20),
        {
            "total_turns": 5.0,
            "approval_without_correction_rate": 1.0,
            "gray_zone_repetition_count": 0.0,
            "false_positive_escalation_rate": 0.0,
            "style_drift_score": 0.0,
            "autonomous_send_rate": 0.0,
            "average_latency_ms": 50.0,
            "promo_sent_count": 1.0,
            "promo_unique_chats": 1.0,
            "promo_repeat_count": 0.0,
        },
    )
    return AdminMetricsService(
        store=store,
        clock=lambda: datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
    )


class TestMetricsKeyboard:
    def test_encode_under_64_bytes(self) -> None:
        for data in (encode_metrics_export(), encode_metrics_back()):
            assert len(data.encode("utf-8")) <= 64

    def test_parse_roundtrip(self) -> None:
        assert parse_metrics_callback(encode_metrics_export()) == "export"
        assert parse_metrics_callback(encode_metrics_back()) == "back"
        assert parse_metrics_callback("mx:x") is None
        assert parse_metrics_callback("a:deadbeef") is None

    def test_keyboard_buttons(self) -> None:
        kb = metrics_keyboard()
        row = kb.inline_keyboard[0]
        assert len(row) == 2
        assert row[0].callback_data == "mx:e"
        assert row[1].callback_data == "mx:b"
        assert "Exportar" in (row[0].text or "")
        assert "Volver" in (row[1].text or "")


class TestMetricsCallbackDispatch:
    @pytest.mark.asyncio
    async def test_export_status(
        self, admin: AdminService, admin_metrics: AdminMetricsService
    ) -> None:
        status = await dispatch_owner_callback(
            admin=admin,
            correct_sessions=CorrectSessionStore(),
            callback_data="mx:e",
            actor_id=OWNER,
            admin_metrics=admin_metrics,
            owner_telegram_id=OWNER,
        )
        assert status == "metrics_export"
        body = await admin_metrics.export_week_json()
        assert "week_start" in body
        assert "total_turns" in body

    @pytest.mark.asyncio
    async def test_back_status(self, admin: AdminService) -> None:
        status = await dispatch_owner_callback(
            admin=admin,
            correct_sessions=CorrectSessionStore(),
            callback_data="mx:b",
            actor_id=OWNER,
            owner_telegram_id=OWNER,
        )
        assert status == "metrics_back"
        assert "/resumen" in ADMIN_MENU_TEXT

    @pytest.mark.asyncio
    async def test_export_unavailable_without_service(self, admin: AdminService) -> None:
        status = await dispatch_owner_callback(
            admin=admin,
            correct_sessions=CorrectSessionStore(),
            callback_data="mx:e",
            actor_id=OWNER,
            admin_metrics=None,
            owner_telegram_id=OWNER,
        )
        assert status == "metrics_unavailable"

    @pytest.mark.asyncio
    async def test_non_owner_forbidden(
        self, admin: AdminService, admin_metrics: AdminMetricsService
    ) -> None:
        status = await dispatch_owner_callback(
            admin=admin,
            correct_sessions=CorrectSessionStore(),
            callback_data="mx:e",
            actor_id=OTHER,
            admin_metrics=admin_metrics,
            owner_telegram_id=OWNER,
        )
        assert status == "forbidden"
