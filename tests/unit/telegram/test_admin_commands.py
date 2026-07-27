"""Admin commands — owner-only VIP add/remove /start /resumen /fp /vip_*."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

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
from diana.application.profile_admin_service import ProfileAdminService
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.infrastructure.db.repositories.profiles import (
    apply_add_note,
    apply_delete_fact,
    apply_delete_note,
    apply_set_fact,
    empty_content,
)
from diana.telegram.handlers.admin import handle_admin_text
from diana.telegram.handlers.callbacks import ADMIN_MENU_TEXT, CorrectSessionStore

OWNER = 999001
OTHER = 111
_WIDE_START = date(2000, 1, 1)
_WIDE_END = date(2100, 1, 1)


class _FakeProfilesRepo:
    def __init__(self) -> None:
        self.rows: dict[UUID, dict] = {}

    async def get_by_vip_id(self, vip_id: UUID) -> dict | None:
        content = self.rows.get(vip_id)
        if content is None:
            return None
        return {
            "vip_id": str(vip_id),
            "tipo": "summary",
            "content": dict(content),
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    async def set_fact(self, vip_id: UUID, key: str, value: str) -> dict:
        base = self.rows.get(vip_id) or empty_content()
        self.rows[vip_id] = apply_set_fact(base, key, value)
        return await self.get_by_vip_id(vip_id)  # type: ignore[return-value]

    async def delete_fact(self, vip_id: UUID, key: str) -> dict | None:
        if vip_id not in self.rows:
            return None
        new_content, _ = apply_delete_fact(self.rows[vip_id], key)
        self.rows[vip_id] = new_content
        return await self.get_by_vip_id(vip_id)

    async def add_note(
        self, vip_id: UUID, text: str, *, date: str | None = None
    ) -> dict:
        note_date = date or "2026-07-27"
        base = self.rows.get(vip_id) or empty_content()
        self.rows[vip_id] = apply_add_note(base, text, note_date)
        return await self.get_by_vip_id(vip_id)  # type: ignore[return-value]

    async def delete_note(self, vip_id: UUID, index: int) -> dict | None:
        if vip_id not in self.rows:
            return None
        new_content, deleted = apply_delete_note(self.rows[vip_id], index)
        if not deleted:
            return None
        self.rows[vip_id] = new_content
        return await self.get_by_vip_id(vip_id)


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
    profiles = _FakeProfilesRepo()
    profile_admin = ProfileAdminService(
        profiles=profiles,
        vips=vips,
        owner_telegram_id=OWNER,
        clock=lambda: datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )
    return {
        "vips": vips,
        "admin": admin,
        "sessions": CorrectSessionStore(),
        "owner": OWNER,
        "metrics_store": metrics_store,
        "admin_metrics": admin_metrics,
        "fp_marks": fp_marks,
        "profiles": profiles,
        "profile_admin": profile_admin,
    }


async def _dispatch(
    g: dict,
    text: str,
    *,
    actor_id: int = OWNER,
    admin_metrics: AdminMetricsService | None | object = ...,
    profile_admin: ProfileAdminService | None | object = ...,
) -> str:
    metrics = g["admin_metrics"] if admin_metrics is ... else admin_metrics
    padmin = g["profile_admin"] if profile_admin is ... else profile_admin
    return await handle_admin_text(
        text=text,
        actor_id=actor_id,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        admin_metrics=metrics,  # type: ignore[arg-type]
        profile_admin=padmin,  # type: ignore[arg-type]
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


@pytest.mark.asyncio
async def test_fp_store_exception_returns_fp_error(admin_ctx: dict) -> None:
    """Store/DB faults map to fp_error (owner system-error UX), not false success."""
    g = admin_ctx

    class _RaisingMarkStore:
        async def mark(self, turn_id, *, kind: str = "false_positive") -> None:  # noqa: ANN001
            raise RuntimeError("db down")

        async def count_in_range(self, week_start, week_end, *, kind: str = "false_positive") -> int:  # noqa: ANN001
            return 0

    g["admin"]._fp_marks = _RaisingMarkStore()  # noqa: SLF001
    turn_id = uuid4()
    assert await _dispatch(g, f"/fp {turn_id}") == "fp_error"


@pytest.mark.asyncio
async def test_fp_store_exception_non_owner_still_ignored(admin_ctx: dict) -> None:
    """Non-owner never reaches mark; store faults must not change fail-closed ignore."""
    g = admin_ctx

    class _RaisingMarkStore:
        async def mark(self, turn_id, *, kind: str = "false_positive") -> None:  # noqa: ANN001
            raise RuntimeError("db down")

        async def count_in_range(self, week_start, week_end, *, kind: str = "false_positive") -> int:  # noqa: ANN001
            return 0

    g["admin"]._fp_marks = _RaisingMarkStore()  # noqa: SLF001
    turn_id = uuid4()
    assert await _dispatch(g, f"/fp {turn_id}", actor_id=OTHER) == "ignored_non_owner"


def test_admin_menu_lists_fp() -> None:
    assert "/fp" in ADMIN_MENU_TEXT


def test_admin_menu_lists_vip_profile_commands() -> None:
    assert "/vip_profile" in ADMIN_MENU_TEXT
    assert "/vip_fact" in ADMIN_MENU_TEXT
    assert "/vip_fact_del" in ADMIN_MENU_TEXT
    assert "/vip_note" in ADMIN_MENU_TEXT
    assert "/vip_note_del" in ADMIN_MENU_TEXT


@pytest.mark.asyncio
async def test_vip_fact_non_owner_ignored(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/vip_fact 555 city BA", actor_id=OTHER) == "ignored_non_owner"


@pytest.mark.asyncio
async def test_vip_profile_usage_missing_args(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/vip_profile") == "vip_profile_usage"


@pytest.mark.asyncio
async def test_vip_profile_empty_after_add(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/add_vip 555 Alice") == "vip_added"
    assert await _dispatch(g, "/vip_profile 555") == "profile_empty"


@pytest.mark.asyncio
async def test_vip_fact_set_then_profile_ok(admin_ctx: dict) -> None:
    g = admin_ctx
    await _dispatch(g, "/add_vip 555 Alice")
    assert await _dispatch(g, "/vip_fact 555 city BA") == "fact_set"
    assert await _dispatch(g, "/vip_profile 555") == "profile_ok"


@pytest.mark.asyncio
async def test_vip_fact_del_success_and_missing(admin_ctx: dict) -> None:
    g = admin_ctx
    await _dispatch(g, "/add_vip 555")
    await _dispatch(g, "/vip_fact 555 city BA")
    assert await _dispatch(g, "/vip_fact_del 555 city") == "fact_deleted"
    assert await _dispatch(g, "/vip_fact_del 555 city") == "fact_missing"


@pytest.mark.asyncio
async def test_vip_note_add_and_delete(admin_ctx: dict) -> None:
    g = admin_ctx
    await _dispatch(g, "/add_vip 555")
    assert await _dispatch(g, "/vip_note 555 met at event") == "note_added"
    assert await _dispatch(g, "/vip_note_del 555 1") == "note_deleted"
    assert await _dispatch(g, "/vip_note_del 555 1") == "note_missing"


@pytest.mark.asyncio
async def test_vip_profile_unknown_vip(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/vip_profile 404") == "vip_not_found"


@pytest.mark.asyncio
async def test_vip_commands_unavailable_without_service(admin_ctx: dict) -> None:
    g = admin_ctx
    assert (
        await _dispatch(g, "/vip_profile 555", profile_admin=None)
        == "profile_admin_unavailable"
    )
    assert (
        await _dispatch(g, "/vip_fact 555 city BA", profile_admin=None)
        == "profile_admin_unavailable"
    )


@pytest.mark.asyncio
async def test_vip_fact_usage(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/vip_fact 555") == "vip_fact_usage"
    assert await _dispatch(g, "/vip_fact 555 city") == "vip_fact_usage"


@pytest.mark.asyncio
async def test_vip_note_and_fact_del_usage(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/vip_note 555") == "vip_note_usage"
    assert await _dispatch(g, "/vip_fact_del 555") == "vip_fact_del_usage"
    assert await _dispatch(g, "/vip_note_del 555") == "vip_note_del_usage"
    assert await _dispatch(g, "/vip_note_del 555 x") == "vip_note_del_usage"


@pytest.mark.asyncio
async def test_vip_fact_value_may_contain_spaces(admin_ctx: dict) -> None:
    """A8: key = single token; value = remainder of line (spaces allowed)."""
    g = admin_ctx
    await _dispatch(g, "/add_vip 555 Alice")
    assert await _dispatch(g, "/vip_fact 555 city Buenos Aires") == "fact_set"
    rec = await g["vips"].get_by_telegram_user_id(555)
    assert rec is not None
    assert g["profiles"].rows[rec.id]["facts"]["city"] == "Buenos Aires"


@pytest.mark.asyncio
async def test_vip_fact_key_is_single_token_rest_is_value(admin_ctx: dict) -> None:
    """F5: multi-word 'key' is not supported — first token is key, rest is value."""
    g = admin_ctx
    await _dispatch(g, "/add_vip 555 Alice")
    assert await _dispatch(g, "/vip_fact 555 favorite city BA") == "fact_set"
    rec = await g["vips"].get_by_telegram_user_id(555)
    assert rec is not None
    assert g["profiles"].rows[rec.id]["facts"] == {"favorite": "city BA"}
    assert "favorite city" not in g["profiles"].rows[rec.id]["facts"]


def test_format_profile_body_empty_and_populated() -> None:
    from diana.telegram.handlers.admin import format_profile_body

    empty = format_profile_body(
        telegram_user_id=555,
        display_name="Alice",
        content=None,
        empty=True,
    )
    assert empty == "VIP 555 (Alice)\nNo profile facts/notes yet."

    body = format_profile_body(
        telegram_user_id=555,
        display_name=None,
        content={
            "facts": {"city": "BA"},
            "notes": [{"date": "2026-07-27", "text": "met at event"}],
        },
        empty=False,
    )
    assert "VIP 555" in body
    assert "city: BA" in body
    assert "1. [2026-07-27] met at event" in body


@pytest.mark.asyncio
async def test_vip_fact_oversize_value_invalid(admin_ctx: dict) -> None:
    """Length cap (SEC): oversize value → invalid at service boundary."""
    from diana.profile_content import MAX_FACT_VALUE_LEN

    g = admin_ctx
    await _dispatch(g, "/add_vip 555")
    huge = "x" * (MAX_FACT_VALUE_LEN + 1)
    assert await _dispatch(g, f"/vip_fact 555 city {huge}") == "invalid"
