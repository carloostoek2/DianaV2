"""Admin commands — owner-only VIP add/remove /start /resumen /fp /vip_*."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
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

    async def delete_by_vip_id(self, vip_id: UUID) -> bool:
        if vip_id not in self.rows:
            return False
        del self.rows[vip_id]
        return True


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
    from diana.application.sandbox import SandboxService

    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "Cold start", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "Warm",
            "facts": {"name": "Mateo"},
            "notes": [],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "Formal",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "Emotional",
            "facts": {},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "Long",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "Adv",
            "facts": {},
            "notes": [],
        },
    }
    sandbox = SandboxService(profiles=MINIMAL_SIX)
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
        "sandbox": sandbox,
        "coordinator": coordinator,
        "turns": turns,
    }


async def _dispatch(
    g: dict,
    text: str,
    *,
    actor_id: int = OWNER,
    admin_metrics: AdminMetricsService | None | object = ...,
    profile_admin: ProfileAdminService | None | object = ...,
    sandbox=...,
    coordinator=...,
) -> str:
    metrics = g["admin_metrics"] if admin_metrics is ... else admin_metrics
    padmin = g["profile_admin"] if profile_admin is ... else profile_admin
    sb = g.get("sandbox") if sandbox is ... else sandbox
    coord = g.get("coordinator") if coordinator is ... else coordinator
    return await handle_admin_text(
        text=text,
        actor_id=actor_id,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        admin_metrics=metrics,  # type: ignore[arg-type]
        profile_admin=padmin,  # type: ignore[arg-type]
        sandbox=sb,
        coordinator=coord,
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
async def test_doctrine_free_text_session_captures_text(admin_ctx: dict) -> None:
    """dr: session → owner free text resolves the gray zone query as doctrine."""
    from diana.application.ports import TurnRecord
    from diana.telegram.handlers.doctrine import DoctrineSessionStore

    g = admin_ctx
    turn_id = uuid4()
    # Real turn in gray_zone so the supervised delivery can transition it.
    await g["turns"].create(
        TurnRecord(
            id=turn_id,
            chat_id=42,
            status="gray_zone",
            channel_type="vip",
            trigger_message_id=7,
        )
    )
    sessions = DoctrineSessionStore()
    sessions.start(OWNER, turn_id)

    class _FakeGrayZone:
        def __init__(self) -> None:
            self.resolved: list[tuple[str, str]] = []

        async def get_open_query_by_turn_id(self, tid: UUID) -> object:
            assert tid == turn_id
            return SimpleNamespace(
                id=uuid4(),
                turn_id=turn_id,
                draft="draft",
                question="q",
                business_connection_id="bc-gray",
            )

        async def resolve_with_doctrine(
            self, query_id: UUID, generalization: str, rule: str
        ) -> object:
            self.resolved.append((generalization, rule))
            return SimpleNamespace(id=uuid4())

        async def confirm_and_apply(self, query_id: UUID, candidate_id: UUID) -> object:
            return SimpleNamespace(id=query_id)

        async def reopen_query(self, query_id: UUID) -> bool:
            return True

    gz = _FakeGrayZone()
    status = await handle_admin_text(
        text="Siempre ofrecer 10% si piden 3 unidades",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        doctrine_sessions=sessions,
        gray_zone=gz,  # type: ignore[arg-type]
        coordinator=g["coordinator"],
    )
    assert status == "resolved"
    assert gz.resolved == [("Siempre ofrecer 10% si piden 3 unidades", "Siempre ofrecer 10% si piden 3 unidades")]
    # Session consumed after capture.
    assert sessions.resolve(OWNER) == ("none", None)
    # The turn moved to pending approval with the owner text as draft.
    stored = await g["turns"].get(turn_id)
    assert stored is not None
    assert stored.status == "pending_approval"


@pytest.mark.asyncio
async def test_doctrine_free_text_expired_session_returns_token(
    admin_ctx: dict,
) -> None:
    from datetime import UTC, datetime, timedelta

    from diana.telegram.handlers.doctrine import DoctrineSessionStore

    g = admin_ctx
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    sessions = DoctrineSessionStore(ttl=timedelta(minutes=15), clock=lambda: now)
    sessions.start(OWNER, uuid4())
    # Advance past TTL.
    now = now + timedelta(minutes=16)

    status = await handle_admin_text(
        text="alguna regla",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        doctrine_sessions=sessions,
        gray_zone=None,
    )
    assert status == "doctrine_session_expired"


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


def test_admin_menu_lists_list_and_rename_vip() -> None:
    assert "/list_vips" in ADMIN_MENU_TEXT
    assert "/rename_vip" in ADMIN_MENU_TEXT


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
async def test_add_vip_schedules_history_seed(admin_ctx: dict) -> None:
    """On VIP allowlist add, schedule Telethon history seed (fire-and-forget)."""
    class _Seed:
        def __init__(self) -> None:
            self.scheduled: list[int] = []

        def schedule_seed_for_new_vip(self, telegram_user_id: int, **_: object) -> None:
            self.scheduled.append(telegram_user_id)

    g = admin_ctx
    seed = _Seed()
    status = await handle_admin_text(
        text="/add_vip 777001",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        history_seed=seed,
    )
    assert status == "vip_added"
    assert seed.scheduled == [777001]


@pytest.mark.asyncio
async def test_add_vip_schedules_backfill_enqueue(admin_ctx: dict) -> None:
    """On VIP allowlist add, the profile backfill is enqueued (fire-and-forget)."""
    class _Queue:
        def __init__(self) -> None:
            self.scheduled: list[int] = []

        def schedule_enqueue(self, telegram_user_id: int, **_: object) -> None:
            self.scheduled.append(telegram_user_id)

    g = admin_ctx
    queue = _Queue()
    status = await handle_admin_text(
        text="/add_vip 777002",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        backfill_queue=queue,
    )
    assert status == "vip_added"
    assert queue.scheduled == [777002]


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
    assert empty == "VIP 555 (Alice)\nSin datos de perfil todavía."

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


# --- list_vips / rename_vip / remove cascade (item2 vip-crud) ---


@pytest.mark.asyncio
async def test_list_vips_non_owner_ignored(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/list_vips", actor_id=OTHER) == "ignored_non_owner"


@pytest.mark.asyncio
async def test_list_vips_empty(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/list_vips") == "vips_empty"


@pytest.mark.asyncio
async def test_list_vips_after_two_adds(admin_ctx: dict) -> None:
    g = admin_ctx
    await _dispatch(g, "/add_vip 100 Alice")
    await _dispatch(g, "/add_vip 200 Bob")
    assert await _dispatch(g, "/list_vips") == "vips_list"


def test_format_vips_list_ids_names_and_no_name() -> None:
    from diana.application.ports import VipRecord
    from diana.telegram.handlers.admin import format_vips_list
    from uuid import uuid4

    records = [
        VipRecord(id=uuid4(), telegram_user_id=100, display_name="Alice", is_active=True),
        VipRecord(id=uuid4(), telegram_user_id=200, display_name=None, is_active=True),
    ]
    body = format_vips_list(records)
    assert "VIPs activos (2):" in body
    assert "100 — Alice" in body
    assert "200 — (sin nombre)" in body


@pytest.mark.asyncio
async def test_rename_vip_success(admin_ctx: dict) -> None:
    g = admin_ctx
    await _dispatch(g, "/add_vip 555 Alice")
    assert await _dispatch(g, "/rename_vip 555 Bob") == "vip_renamed"
    rec = await g["vips"].get_by_telegram_user_id(555)
    assert rec is not None
    assert rec.display_name == "Bob"


@pytest.mark.asyncio
async def test_rename_vip_missing(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/rename_vip 404 Bob") == "vip_not_found"


@pytest.mark.asyncio
async def test_rename_vip_usage_bad_args(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/rename_vip") == "rename_vip_usage"
    assert await _dispatch(g, "/rename_vip 555") == "rename_vip_usage"
    await _dispatch(g, "/add_vip 555")
    huge = "x" * 65
    assert await _dispatch(g, f"/rename_vip 555 {huge}") == "rename_vip_usage"


@pytest.mark.asyncio
async def test_remove_vip_purges_profile_when_profile_admin_wired(
    admin_ctx: dict,
) -> None:
    g = admin_ctx
    await _dispatch(g, "/add_vip 555 Alice")
    await _dispatch(g, "/vip_fact 555 city BA")
    rec = await g["vips"].get_by_telegram_user_id(555)
    assert rec is not None
    assert rec.id in g["profiles"].rows

    assert await _dispatch(g, "/remove_vip 555") == "vip_removed"
    assert await g["vips"].is_allowed(555) is False
    assert rec.id not in g["profiles"].rows
    assert await g["profiles"].get_by_vip_id(rec.id) is None


@pytest.mark.asyncio
async def test_remove_vip_without_profile_admin_still_deactivates(
    admin_ctx: dict,
) -> None:
    g = admin_ctx
    await _dispatch(g, "/add_vip 555 Alice")
    assert (
        await _dispatch(g, "/remove_vip 555", profile_admin=None) == "vip_removed"
    )
    assert await g["vips"].is_allowed(555) is False


@pytest.mark.asyncio
async def test_remove_vip_purge_exception_still_vip_removed(
    admin_ctx: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """SUG-1: after deactivate, purge faults must not hide vip_removed."""
    import logging

    g = admin_ctx
    await _dispatch(g, "/add_vip 555 Alice")
    await _dispatch(g, "/vip_fact 555 city BA")

    async def _boom(*_a, **_k):  # noqa: ANN001
        raise RuntimeError("db down")

    g["profile_admin"].purge_profile_for_telegram_user = _boom  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR, logger="diana.telegram"):
        assert await _dispatch(g, "/remove_vip 555") == "vip_removed"
    assert await g["vips"].is_allowed(555) is False
    assert any(r.getMessage() == "vip_remove_purge_failed" for r in caplog.records)


def test_is_private_owner_message_gate() -> None:
    from aiogram.types import Chat, Message, User

    from diana.telegram.handlers.admin import is_private_owner_message

    owner = User(id=OWNER, is_bot=False, first_name="O")
    other = User(id=OTHER, is_bot=False, first_name="X")
    private = Message(
        message_id=1,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=owner,
        text="/list_vips",
    )
    group = Message(
        message_id=2,
        date=0,
        chat=Chat(id=-1001, type="group"),
        from_user=owner,
        text="/list_vips",
    )
    supergroup = Message(
        message_id=3,
        date=0,
        chat=Chat(id=-1002, type="supergroup"),
        from_user=owner,
        text="/list_vips",
    )
    non_owner_private = Message(
        message_id=4,
        date=0,
        chat=Chat(id=OTHER, type="private"),
        from_user=other,
        text="/list_vips",
    )
    assert is_private_owner_message(private, OWNER) is True
    assert is_private_owner_message(group, OWNER) is False
    assert is_private_owner_message(supergroup, OWNER) is False
    assert is_private_owner_message(non_owner_private, OWNER) is False


def _router_handler(router, name: str):  # noqa: ANN001
    for h in router.message.handlers:
        if getattr(h.callback, "__name__", None) == name:
            return h.callback
    raise AssertionError(f"handler not found: {name}")


def _admin_message(
    text: str,
    *,
    chat_type: str = "private",
    user_id: int = OWNER,
    chat_id: int | None = None,
):
    from aiogram.types import Chat, Message, User
    from unittest.mock import AsyncMock

    cid = chat_id if chat_id is not None else (
        user_id if chat_type == "private" else -100555
    )
    msg = Message(
        message_id=1,
        date=0,
        chat=Chat(id=cid, type=chat_type),
        from_user=User(id=user_id, is_bot=False, first_name="O"),
        text=text,
    )
    object.__setattr__(msg, "answer", AsyncMock())
    return msg


@pytest.mark.asyncio
async def test_list_vips_group_chat_silently_ignored(admin_ctx: dict) -> None:
    """SEC-VIP-01: owner in non-private chat must not dump allowlist."""
    from diana.telegram.handlers.admin import build_admin_router

    g = admin_ctx
    await g["vips"].add(100, display_name="Alice")
    router = build_admin_router(
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        profile_admin=g["profile_admin"],
    )
    on_list = _router_handler(router, "on_list_vips")
    msg = _admin_message("/list_vips", chat_type="group")
    await on_list(msg)
    msg.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_vip_group_chat_silently_ignored(admin_ctx: dict) -> None:
    """SEC-VIP-01: owner in group must not deactivate / purge."""
    from diana.telegram.handlers.admin import build_admin_router

    g = admin_ctx
    await g["vips"].add(555, display_name="Alice")
    await g["profile_admin"].set_fact(OWNER, 555, "city", "BA")
    rec = await g["vips"].get_by_telegram_user_id(555)
    assert rec is not None

    router = build_admin_router(
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        profile_admin=g["profile_admin"],
    )
    on_rm = _router_handler(router, "on_remove_vip")
    msg = _admin_message("/remove_vip 555", chat_type="supergroup")
    await on_rm(msg)
    msg.answer.assert_not_awaited()
    assert await g["vips"].is_allowed(555) is True
    assert rec.id in g["profiles"].rows


@pytest.mark.asyncio
async def test_list_vips_private_owner_answers(admin_ctx: dict) -> None:
    from diana.telegram.handlers.admin import build_admin_router

    g = admin_ctx
    await g["vips"].add(100, display_name="Alice")
    router = build_admin_router(
        owner_telegram_id=OWNER,
        vips=g["vips"],
        admin=g["admin"],
        correct_sessions=g["sessions"],
        profile_admin=g["profile_admin"],
    )
    on_list = _router_handler(router, "on_list_vips")
    msg = _admin_message("/list_vips", chat_type="private")
    await on_list(msg)
    msg.answer.assert_awaited()
    body = msg.answer.await_args.args[0]
    assert "100 — Alice" in body


# ---------------------------------------------------------------------------
# /sandbox commands (item4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_non_owner_ignored(admin_ctx: dict) -> None:
    assert await _dispatch(admin_ctx, "/sandbox", actor_id=OTHER) == "ignored_non_owner"


@pytest.mark.asyncio
async def test_sandbox_unavailable_when_none(admin_ctx: dict) -> None:
    assert await _dispatch(admin_ctx, "/sandbox", sandbox=None) == "sandbox_unavailable"


@pytest.mark.asyncio
async def test_sandbox_help(admin_ctx: dict) -> None:
    assert await _dispatch(admin_ctx, "/sandbox") == "sandbox_help"


@pytest.mark.asyncio
async def test_sandbox_on_off_happy(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/sandbox on 555") == "sandbox_on"
    assert g["sandbox"].is_active(555) is True
    assert g["sandbox"].get_profile(555) == "nuevo"
    assert await _dispatch(g, "/sandbox off 555") == "sandbox_off"
    assert g["sandbox"].is_active(555) is False


@pytest.mark.asyncio
async def test_sandbox_on_with_profile(admin_ctx: dict) -> None:
    g = admin_ctx
    assert await _dispatch(g, "/sandbox on 555 cercano") == "sandbox_on"
    assert g["sandbox"].get_profile(555) == "cercano"


@pytest.mark.asyncio
async def test_sandbox_on_unknown_profile_error(admin_ctx: dict) -> None:
    assert await _dispatch(admin_ctx, "/sandbox on 555 nope") == "sandbox_error"


@pytest.mark.asyncio
async def test_sandbox_off_not_active(admin_ctx: dict) -> None:
    assert await _dispatch(admin_ctx, "/sandbox off 999") == "sandbox_not_active"


@pytest.mark.asyncio
async def test_sandbox_perfil_perfiles_estado(admin_ctx: dict) -> None:
    g = admin_ctx
    await _dispatch(g, "/sandbox on 100 cercano")
    assert await _dispatch(g, "/sandbox perfil distante") == "sandbox_perfil"
    assert g["sandbox"].get_profile(100) == "distante"
    assert await _dispatch(g, "/sandbox perfiles") == "sandbox_perfiles"
    assert await _dispatch(g, "/sandbox estado") == "sandbox_estado"


@pytest.mark.asyncio
async def test_sandbox_reset_requires_focus(admin_ctx: dict) -> None:
    assert await _dispatch(admin_ctx, "/sandbox reset") == "sandbox_not_active"


@pytest.mark.asyncio
async def test_sandbox_reset_calls_coordinator_keeps_session(admin_ctx: dict) -> None:
    from unittest.mock import AsyncMock

    g = admin_ctx
    await _dispatch(g, "/sandbox on 200 nuevo")
    coord = AsyncMock()
    coord.reset_chat_session = AsyncMock(return_value=1)
    assert await _dispatch(g, "/sandbox reset", coordinator=coord) == "sandbox_reset"
    coord.reset_chat_session.assert_awaited_once()
    kwargs = coord.reset_chat_session.await_args
    assert kwargs.args[0] == 200 or kwargs.kwargs.get("chat_id") == 200
    assert g["sandbox"].is_active(200) is True


@pytest.mark.asyncio
async def test_sandbox_usage_on_bad_args(admin_ctx: dict) -> None:
    assert await _dispatch(admin_ctx, "/sandbox on") == "sandbox_usage"
    assert await _dispatch(admin_ctx, "/sandbox perfil") == "sandbox_usage"


@pytest.mark.asyncio
async def test_menu_documents_sandbox() -> None:
    assert "/sandbox" in ADMIN_MENU_TEXT
    assert "perfil" in ADMIN_MENU_TEXT or "on|off" in ADMIN_MENU_TEXT
