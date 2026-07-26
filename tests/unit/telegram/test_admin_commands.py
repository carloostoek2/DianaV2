"""Admin commands — owner-only VIP add/remove /start /resumen /fp."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

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
    InMemoryVipStore,
)
from diana.application.owner_marks import InMemoryOwnerMarkStore
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.telegram.handlers.admin import handle_admin_text
from diana.telegram.handlers.callbacks import ADMIN_MENU_TEXT, CorrectSessionStore

OWNER = 999001
OTHER = 111
_WIDE_START = date(2000, 1, 1)
_WIDE_END = date(2100, 1, 1)


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
def admin_ctx() -> dict:
    vips = InMemoryVipStore()
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    behavior = BehaviorEngine(
        FakeTelegramActuator(),
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER,
    )
    fp_marks = InMemoryOwnerMarkStore()
    admin._fp_marks = fp_marks  # noqa: SLF001
    metrics_store = _FakeMetricsStore()
    admin_metrics = AdminMetricsService(
        store=metrics_store,
        clock=lambda: datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
    )
    return {
        "vips": vips,
        "admin": admin,
        "sessions": CorrectSessionStore(),
        "owner": OWNER,
        "metrics_store": metrics_store,
        "admin_metrics": admin_metrics,
        "fp_marks": fp_marks,
    }


async def _dispatch(
    g: dict,
    text: str,
    *,
    actor_id: int = OWNER,
    admin_metrics: AdminMetricsService | None | object = ...,
) -> str:
    metrics = g["admin_metrics"] if admin_metrics is ... else admin_metrics
    return await handle_admin_text(
        text=text,
        actor_id=actor_id,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        admin_metrics=metrics,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_start_menu_owner(admin_ctx: dict) -> None:
    g = admin_ctx
    status = await handle_admin_text(
        text="/start",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert status == "menu"


@pytest.mark.asyncio
async def test_non_owner_ignored(admin_ctx: dict) -> None:
    g = admin_ctx
    status = await handle_admin_text(
        text="/add_vip 123",
        actor_id=OTHER,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert status == "ignored_non_owner"
    assert await g["vips"].is_allowed(123) is False


@pytest.mark.asyncio
async def test_add_and_remove_vip(admin_ctx: dict) -> None:
    g = admin_ctx
    assert (
        await handle_admin_text(
            text="/add_vip 555 Alice",
            actor_id=OWNER,
            owner_telegram_id=OWNER,
            vips=g["vips"],
            admin=g["admin"],
            correct_sessions=g["sessions"],
        )
        == "vip_added"
    )
    assert await g["vips"].is_allowed(555) is True
    assert (
        await handle_admin_text(
            text="/remove_vip 555",
            actor_id=OWNER,
            owner_telegram_id=OWNER,
            vips=g["vips"],
            admin=g["admin"],
            correct_sessions=g["sessions"],
        )
        == "vip_removed"
    )
    assert await g["vips"].is_allowed(555) is False


@pytest.mark.asyncio
async def test_resumen_owner_ok(admin_ctx: dict) -> None:
    g = admin_ctx
    week = date(2026, 7, 20)
    g["metrics_store"].seed(
        week,
        {
            "total_turns": 10.0,
            "approval_without_correction_rate": 0.8,
            "gray_zone_repetition_count": 0.0,
            "false_positive_escalation_rate": 0.0,
            "style_drift_score": 0.01,
            "autonomous_send_rate": 0.1,
            "average_latency_ms": 100.0,
            "promo_sent_count": 0.0,
            "promo_unique_chats": 0.0,
            "promo_repeat_count": 0.0,
        },
    )
    assert await _dispatch(g, "/resumen") == "metrics_ok"


@pytest.mark.asyncio
async def test_metricas_alias(admin_ctx: dict) -> None:
    g = admin_ctx
    g["metrics_store"].seed(
        date(2026, 7, 20),
        {"total_turns": 1.0, "approval_without_correction_rate": 1.0},
    )
    assert await _dispatch(g, "/metricas") == "metrics_ok"


@pytest.mark.asyncio
async def test_resumen_empty_week(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/resumen") == "metrics_empty"


@pytest.mark.asyncio
async def test_resumen_unavailable_when_service_none(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/resumen", admin_metrics=None) == "metrics_unavailable"


@pytest.mark.asyncio
async def test_resumen_non_owner_ignored(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/resumen", actor_id=OTHER) == "ignored_non_owner"


@pytest.mark.asyncio
async def test_fp_owner_marks_turn(admin_ctx: dict) -> None:
    g = admin_ctx
    turn_id = uuid4()
    assert await _dispatch(g, f"/fp {turn_id}") == "fp_marked"
    assert await g["fp_marks"].count_in_range(_WIDE_START, _WIDE_END) == 1


@pytest.mark.asyncio
async def test_fp_non_owner_ignored(admin_ctx: dict) -> None:
    g = admin_ctx
    turn_id = uuid4()
    assert await _dispatch(g, f"/fp {turn_id}", actor_id=OTHER) == "ignored_non_owner"
    assert await g["fp_marks"].count_in_range(_WIDE_START, _WIDE_END) == 0


@pytest.mark.asyncio
async def test_fp_usage_missing_arg(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/fp") == "fp_usage"
    assert await g["fp_marks"].count_in_range(_WIDE_START, _WIDE_END) == 0


@pytest.mark.asyncio
async def test_fp_usage_invalid_uuid(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/fp not-a-uuid") == "fp_usage"
    assert await g["fp_marks"].count_in_range(_WIDE_START, _WIDE_END) == 0


@pytest.mark.asyncio
async def test_fp_unavailable_without_store(admin_ctx: dict) -> None:
    g = admin_ctx
    g["admin"]._fp_marks = None  # noqa: SLF001
    turn_id = uuid4()
    assert await _dispatch(g, f"/fp {turn_id}") == "fp_unavailable"


@pytest.mark.asyncio
async def test_fp_bot_suffix(admin_ctx: dict) -> None:
    g = admin_ctx
    turn_id = uuid4()
    assert await _dispatch(g, f"/fp@SomeBot {turn_id}") == "fp_marked"
    assert await g["fp_marks"].count_in_range(_WIDE_START, _WIDE_END) == 1


@pytest.mark.asyncio
async def test_fp_idempotent_remark(admin_ctx: dict) -> None:
    g = admin_ctx
    turn_id = uuid4()
    assert await _dispatch(g, f"/fp {turn_id}") == "fp_marked"
    assert await _dispatch(g, f"/fp {turn_id}") == "fp_marked"
    assert await g["fp_marks"].count_in_range(_WIDE_START, _WIDE_END) == 1


def test_admin_menu_lists_fp() -> None:
    assert "/fp" in ADMIN_MENU_TEXT
