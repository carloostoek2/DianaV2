"""RecontactService — schedule lifecycle, eligibility, AMS deliver vs supervised skip."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from diana.application.autonomous_mode_service import AutonomousModeService
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryPendingApprovalStore,
    InMemoryTurnStore,
    InMemoryVipStore,
)
from diana.application.ports import (
    ApprovalRecord,
    DeliveryContext,
    DeliveryResult,
    RecontactScheduleRecord,
    TurnRecord,
    VipRecord,
)
from diana.application.recontact_service import (
    RecontactService,
    render_template,
)


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now = self._now + timedelta(**kwargs)


class FakeConfig:
    def __init__(
        self,
        *,
        inactivity_days: int = 7,
        templates: list[str] | None = None,
    ) -> None:
        self._cfg = {
            "inactivity_days": inactivity_days,
            "templates": templates
            or ["Hola {nombre}, ¿cómo andás?"],
        }

    async def get_recontact_config(self) -> dict:
        return dict(self._cfg)


class InMemoryRecontactScheduleStore:
    """Dict-backed RecontactScheduleStore for unit tests."""

    def __init__(self) -> None:
        self.rows: dict[UUID, RecontactScheduleRecord] = {}

    async def upsert_pending(
        self,
        vip_id: UUID,
        last_contact_at: datetime,
        next_contact_at: datetime | None,
    ) -> RecontactScheduleRecord:
        for row in self.rows.values():
            if row.vip_id == vip_id and row.status == "pending":
                updated = row.model_copy(
                    update={
                        "last_contact_at": last_contact_at,
                        "next_contact_at": next_contact_at,
                    }
                )
                self.rows[row.id] = updated
                return updated.model_copy(deep=True)
        rec = RecontactScheduleRecord(
            id=uuid4(),
            vip_id=vip_id,
            last_contact_at=last_contact_at,
            next_contact_at=next_contact_at,
            status="pending",
        )
        self.rows[rec.id] = rec
        return rec.model_copy(deep=True)

    async def get_pending_by_vip(self, vip_id: UUID) -> RecontactScheduleRecord | None:
        for row in self.rows.values():
            if row.vip_id == vip_id and row.status == "pending":
                return row.model_copy(deep=True)
        return None

    async def list_due(self, now: datetime) -> list[RecontactScheduleRecord]:
        out: list[RecontactScheduleRecord] = []
        for row in self.rows.values():
            if (
                row.status == "pending"
                and row.next_contact_at is not None
                and row.next_contact_at <= now
            ):
                out.append(row.model_copy(deep=True))
        return out

    async def cancel_pending(self, vip_id: UUID) -> bool:
        for rid, row in list(self.rows.items()):
            if row.vip_id == vip_id and row.status == "pending":
                self.rows[rid] = row.model_copy(update={"status": "cancelled"})
                return True
        return False

    async def mark_done(self, schedule_id: UUID) -> bool:
        row = self.rows.get(schedule_id)
        if row is None:
            return False
        self.rows[schedule_id] = row.model_copy(update={"status": "done"})
        return True


class FakeBehavior:
    def __init__(self, *, success: bool = True) -> None:
        self.deliver_calls: list[tuple[list[str], DeliveryContext, UUID]] = []
        self.success = success

    async def deliver(
        self,
        texts: list[str],
        ctx: DeliveryContext,
        turn_id: UUID,
        decision=None,
    ) -> DeliveryResult:
        self.deliver_calls.append((list(texts), ctx, turn_id))
        return DeliveryResult(
            success=self.success,
            message_ids=[9001] if self.success else [],
            error=None if self.success else "send_failed",
        )

    async def cancel_pending(self, chat_id: int, reason: str = "new_message") -> None:
        return None


class FakeRouteResolver:
    def __init__(self, routes: dict[UUID, tuple[int, str]] | None = None) -> None:
        self._routes = routes or {}

    async def resolve(self, vip_id: UUID) -> tuple[int, str] | None:
        return self._routes.get(vip_id)


def _ams(
    *,
    feature: bool = True,
    global_mode: str = "autonomous",
    vip_store: InMemoryVipStore | None = None,
    notifier: FakeOwnerNotifier | None = None,
) -> AutonomousModeService:
    return AutonomousModeService(
        feature_autonomous_mode=feature,
        global_mode=global_mode,
        vip_store=vip_store or InMemoryVipStore(),
        notifier=notifier or FakeOwnerNotifier(),
    )


async def _seed_vip(
    store: InMemoryVipStore,
    *,
    display_name: str | None = "Ana",
    is_active: bool = True,
    paused_until: datetime | None = None,
    frozen_until: datetime | None = None,
    auto_send: bool = False,
    telegram_user_id: int | None = None,
) -> VipRecord:
    tg = telegram_user_id if telegram_user_id is not None else uuid4().int % 1_000_000_000
    rec = await store.add(tg, display_name=display_name)
    updated = rec.model_copy(
        update={
            "is_active": is_active,
            "paused_until": paused_until,
            "frozen_until": frozen_until,
            "auto_send": auto_send,
        }
    )
    await store._upsert(updated)  # noqa: SLF001 — test seed
    return updated


def _make_service(
    *,
    feature: bool = True,
    schedules: InMemoryRecontactScheduleStore | None = None,
    vips: InMemoryVipStore | None = None,
    config: FakeConfig | None = None,
    approvals: InMemoryPendingApprovalStore | None = None,
    ams: AutonomousModeService | None = None,
    behavior: FakeBehavior | None = None,
    turns: InMemoryTurnStore | None = None,
    route_resolver: FakeRouteResolver | None = None,
    notifier: FakeOwnerNotifier | None = None,
    clock: FakeClock | None = None,
    delivery_mode: str = "supervised",
    has_open_gray_zone=None,
    is_sandbox_vip=None,
) -> tuple[RecontactService, dict]:
    schedules = schedules or InMemoryRecontactScheduleStore()
    vips = vips or InMemoryVipStore()
    config = config or FakeConfig()
    approvals = approvals or InMemoryPendingApprovalStore()
    notifier = notifier or FakeOwnerNotifier()
    clock = clock or FakeClock()
    behavior = behavior or FakeBehavior()
    turns = turns or InMemoryTurnStore()
    route_resolver = route_resolver or FakeRouteResolver()
    ams = ams or _ams(vip_store=vips, notifier=notifier)
    svc = RecontactService(
        feature_recontact_enabled=feature,
        schedules=schedules,
        vips=vips,
        config=config,
        approvals=approvals,
        ams=ams,
        behavior=behavior,
        turns=turns,
        route_resolver=route_resolver,
        notifier=notifier,
        clock=clock,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        has_open_gray_zone=has_open_gray_zone,
        is_sandbox_vip=is_sandbox_vip,
    )
    deps = {
        "schedules": schedules,
        "vips": vips,
        "config": config,
        "approvals": approvals,
        "ams": ams,
        "behavior": behavior,
        "turns": turns,
        "route_resolver": route_resolver,
        "notifier": notifier,
        "clock": clock,
    }
    return svc, deps


# ---------------------------------------------------------------------------
# Template helper
# ---------------------------------------------------------------------------


def test_render_template_nombre_and_producto() -> None:
    assert (
        render_template("Hola {nombre}, re: {producto}", nombre="Ana", producto="kit")
        == "Hola Ana, re: kit"
    )
    assert render_template("Hola {nombre}", nombre="vos") == "Hola vos"
    assert (
        render_template("Hola {nombre} {producto}", nombre="Ana") == "Hola Ana "
    )


# ---------------------------------------------------------------------------
# Flag-off no-ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_schedule_returns_none() -> None:
    svc, deps = _make_service(feature=False)
    vip = await _seed_vip(deps["vips"])
    assert await svc.schedule_recontact(vip.id) is None
    assert await deps["schedules"].get_pending_by_vip(vip.id) is None


@pytest.mark.asyncio
async def test_flag_off_cancel_returns_false() -> None:
    svc, _ = _make_service(feature=False)
    assert await svc.cancel_recontact(uuid4()) is False


@pytest.mark.asyncio
async def test_flag_off_is_blocked_false() -> None:
    svc, _ = _make_service(feature=False)
    assert await svc.is_blocked(uuid4()) is False


@pytest.mark.asyncio
async def test_flag_off_get_due_empty() -> None:
    svc, _ = _make_service(feature=False)
    assert await svc.get_due_vips() == []


@pytest.mark.asyncio
async def test_flag_off_execute_disabled() -> None:
    svc, deps = _make_service(feature=False)
    assert await svc.execute_recontact(uuid4()) == "disabled"
    assert deps["behavior"].deliver_calls == []


# ---------------------------------------------------------------------------
# schedule / cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_recontact_uses_inactivity_days() -> None:
    clock = FakeClock()
    svc, deps = _make_service(
        config=FakeConfig(inactivity_days=10),
        clock=clock,
    )
    vip = await _seed_vip(deps["vips"])
    rec = await svc.schedule_recontact(vip.id)
    assert rec is not None
    assert rec.status == "pending"
    assert rec.vip_id == vip.id
    assert rec.next_contact_at == clock.now() + timedelta(days=10)
    assert rec.last_contact_at == clock.now()


@pytest.mark.asyncio
async def test_schedule_recontact_upserts_pending() -> None:
    clock = FakeClock()
    svc, deps = _make_service(clock=clock)
    vip = await _seed_vip(deps["vips"])
    first = await svc.schedule_recontact(vip.id)
    clock.advance(days=1)
    second = await svc.schedule_recontact(vip.id)
    assert first is not None and second is not None
    assert first.id == second.id
    assert second.last_contact_at == clock.now()


@pytest.mark.asyncio
async def test_cancel_recontact_marks_cancelled() -> None:
    svc, deps = _make_service()
    vip = await _seed_vip(deps["vips"])
    await svc.schedule_recontact(vip.id)
    assert await svc.cancel_recontact(vip.id) is True
    assert await deps["schedules"].get_pending_by_vip(vip.id) is None
    assert await svc.cancel_recontact(vip.id) is False


# ---------------------------------------------------------------------------
# is_blocked matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_blocked_missing_vip() -> None:
    svc, _ = _make_service()
    assert await svc.is_blocked(uuid4()) is True


@pytest.mark.asyncio
async def test_is_blocked_inactive_vip() -> None:
    svc, deps = _make_service()
    vip = await _seed_vip(deps["vips"], is_active=False)
    assert await svc.is_blocked(vip.id) is True


@pytest.mark.asyncio
async def test_is_blocked_paused_until_future() -> None:
    clock = FakeClock()
    svc, deps = _make_service(clock=clock)
    vip = await _seed_vip(
        deps["vips"],
        paused_until=clock.now() + timedelta(hours=2),
    )
    assert await svc.is_blocked(vip.id) is True


@pytest.mark.asyncio
async def test_is_blocked_paused_until_past_not_blocked() -> None:
    clock = FakeClock()
    svc, deps = _make_service(clock=clock)
    vip = await _seed_vip(
        deps["vips"],
        paused_until=clock.now() - timedelta(hours=1),
    )
    assert await svc.is_blocked(vip.id) is False


@pytest.mark.asyncio
async def test_is_blocked_frozen_until_future() -> None:
    clock = FakeClock()
    svc, deps = _make_service(clock=clock)
    vip = await _seed_vip(
        deps["vips"],
        frozen_until=clock.now() + timedelta(days=1),
    )
    assert await svc.is_blocked(vip.id) is True


@pytest.mark.asyncio
async def test_is_blocked_pending_approval() -> None:
    svc, deps = _make_service()
    vip = await _seed_vip(deps["vips"])
    await deps["approvals"].create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=uuid4(),
            chat_id=1001,
            business_connection_id="bc-1",
            draft_text="draft",
            status="waiting",
            vip_id=vip.id,
        )
    )
    assert await svc.is_blocked(vip.id) is True


@pytest.mark.asyncio
async def test_is_blocked_claimed_approval() -> None:
    """R1: claimed approvals also block recontact (not only waiting)."""
    svc, deps = _make_service()
    vip = await _seed_vip(deps["vips"])
    turn_id = uuid4()
    await deps["approvals"].create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=1001,
            business_connection_id="bc-1",
            draft_text="draft",
            status="waiting",
            vip_id=vip.id,
        )
    )
    claimed = await deps["approvals"].claim_waiting(turn_id)
    assert claimed is not None and claimed.status == "claimed"
    assert await svc.is_blocked(vip.id) is True




@pytest.mark.asyncio
async def test_is_blocked_open_gray_zone_hook() -> None:
    vips = InMemoryVipStore()
    vip = await _seed_vip(vips)
    other = await _seed_vip(vips, telegram_user_id=99_001)

    async def checker(vip_id: UUID) -> bool:
        return vip_id == vip.id

    svc, _ = _make_service(vips=vips, has_open_gray_zone=checker)
    assert await svc.is_blocked(vip.id) is True
    assert await svc.is_blocked(other.id) is False


@pytest.mark.asyncio
async def test_is_blocked_sandbox_hook() -> None:
    svc, deps = _make_service()
    vip = await _seed_vip(deps["vips"])

    async def sandbox(vip_id: UUID) -> bool:
        return vip_id == vip.id

    svc._is_sandbox_vip = sandbox  # noqa: SLF001
    assert await svc.is_blocked(vip.id) is True


@pytest.mark.asyncio
async def test_is_blocked_healthy_vip_false() -> None:
    svc, deps = _make_service()
    vip = await _seed_vip(deps["vips"])
    assert await svc.is_blocked(vip.id) is False


# ---------------------------------------------------------------------------
# get_due_vips
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_due_vips_filters_blocked_and_dedupes() -> None:
    clock = FakeClock()
    schedules = InMemoryRecontactScheduleStore()
    svc, deps = _make_service(schedules=schedules, clock=clock)
    ok = await _seed_vip(deps["vips"], telegram_user_id=1)
    blocked = await _seed_vip(
        deps["vips"],
        telegram_user_id=2,
        frozen_until=clock.now() + timedelta(days=1),
    )
    past = clock.now() - timedelta(hours=1)
    await schedules.upsert_pending(ok.id, past, past)
    await schedules.upsert_pending(blocked.id, past, past)
    # second due row same vip should not duplicate (upsert keeps one pending)
    due = await svc.get_due_vips()
    assert due == [ok.id]


@pytest.mark.asyncio
async def test_get_due_vips_ignores_future_schedules() -> None:
    clock = FakeClock()
    schedules = InMemoryRecontactScheduleStore()
    svc, deps = _make_service(schedules=schedules, clock=clock)
    vip = await _seed_vip(deps["vips"])
    future = clock.now() + timedelta(days=3)
    await schedules.upsert_pending(vip.id, clock.now(), future)
    assert await svc.get_due_vips() == []


# ---------------------------------------------------------------------------
# execute_recontact — AMS deliver vs supervised skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_ams_on_delivers_and_reschedules() -> None:
    clock = FakeClock()
    schedules = InMemoryRecontactScheduleStore()
    vips = InMemoryVipStore()
    vip = await _seed_vip(vips, display_name="Ana")
    past = clock.now() - timedelta(days=1)
    await schedules.upsert_pending(vip.id, past, past)
    route = FakeRouteResolver({vip.id: (42_001, "bc-vip")})
    behavior = FakeBehavior(success=True)
    ams = _ams(feature=True, global_mode="autonomous", vip_store=vips)
    svc, deps = _make_service(
        schedules=schedules,
        vips=vips,
        ams=ams,
        behavior=behavior,
        route_resolver=route,
        clock=clock,
        config=FakeConfig(
            inactivity_days=7,
            templates=["Hola {nombre}, ¿cómo andás?"],
        ),
        delivery_mode="autonomous",
    )

    status = await svc.execute_recontact(vip.id)
    assert status == "delivered"
    assert len(behavior.deliver_calls) == 1
    texts, ctx, turn_id = behavior.deliver_calls[0]
    assert texts == ["Hola Ana, ¿cómo andás?"]
    assert ctx.chat_id == 42_001
    assert ctx.business_connection_id == "bc-vip"
    assert ctx.vip_id == vip.id
    assert ctx.mode == "autonomous"
    assert ctx.is_frozen is False

    turn = await deps["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "delivered"
    assert turn.vip_id == vip.id

    # old schedule done; next pending created
    pending = await schedules.get_pending_by_vip(vip.id)
    assert pending is not None
    assert pending.next_contact_at == clock.now() + timedelta(days=7)
    done_rows = [r for r in schedules.rows.values() if r.status == "done"]
    assert len(done_rows) == 1


@pytest.mark.asyncio
async def test_execute_ams_off_skips_deliver_and_notifies() -> None:
    clock = FakeClock()
    schedules = InMemoryRecontactScheduleStore()
    vips = InMemoryVipStore()
    notifier = FakeOwnerNotifier()
    vip = await _seed_vip(vips, display_name="Lucía", auto_send=False)
    past = clock.now() - timedelta(hours=2)
    await schedules.upsert_pending(vip.id, past, past)
    route = FakeRouteResolver({vip.id: (55, "bc-x")})
    behavior = FakeBehavior()
    # L1 on but supervised + auto_send false → L2 off
    ams = _ams(
        feature=True,
        global_mode="supervised",
        vip_store=vips,
        notifier=notifier,
    )
    svc, _ = _make_service(
        schedules=schedules,
        vips=vips,
        ams=ams,
        behavior=behavior,
        route_resolver=route,
        notifier=notifier,
        clock=clock,
        config=FakeConfig(templates=["Hola {nombre}"]),
    )

    status = await svc.execute_recontact(vip.id)
    assert status == "supervised_skipped"
    assert behavior.deliver_calls == []
    assert len(notifier.infos) == 1
    info_text = notifier.infos[0][0]
    assert "Lucía" in info_text or "Hola Lucía" in info_text
    assert "Hola Lucía" in info_text

    pending = await schedules.get_pending_by_vip(vip.id)
    assert pending is not None
    assert pending.next_contact_at == clock.now() + timedelta(days=7)


@pytest.mark.asyncio
async def test_execute_blocked_no_deliver_schedule_stays_pending() -> None:
    clock = FakeClock()
    schedules = InMemoryRecontactScheduleStore()
    vips = InMemoryVipStore()
    vip = await _seed_vip(
        vips,
        frozen_until=clock.now() + timedelta(days=2),
    )
    past = clock.now() - timedelta(hours=1)
    await schedules.upsert_pending(vip.id, past, past)
    behavior = FakeBehavior()
    svc, _ = _make_service(
        schedules=schedules,
        vips=vips,
        behavior=behavior,
        clock=clock,
        route_resolver=FakeRouteResolver({vip.id: (1, "bc")}),
        ams=_ams(feature=True, global_mode="autonomous", vip_store=vips),
    )
    status = await svc.execute_recontact(vip.id)
    assert status == "blocked"
    assert behavior.deliver_calls == []
    pending = await schedules.get_pending_by_vip(vip.id)
    assert pending is not None
    assert pending.status == "pending"
    assert pending.next_contact_at == past


@pytest.mark.asyncio
async def test_execute_no_route_pushes_next_contact() -> None:
    clock = FakeClock()
    schedules = InMemoryRecontactScheduleStore()
    vips = InMemoryVipStore()
    vip = await _seed_vip(vips)
    past = clock.now() - timedelta(hours=1)
    await schedules.upsert_pending(vip.id, past, past)
    behavior = FakeBehavior()
    svc, _ = _make_service(
        schedules=schedules,
        vips=vips,
        behavior=behavior,
        clock=clock,
        route_resolver=FakeRouteResolver({}),  # no route
        ams=_ams(feature=True, global_mode="autonomous", vip_store=vips),
        config=FakeConfig(inactivity_days=5),
    )
    status = await svc.execute_recontact(vip.id)
    assert status == "no_route"
    assert behavior.deliver_calls == []
    pending = await schedules.get_pending_by_vip(vip.id)
    assert pending is not None
    assert pending.status == "pending"
    assert pending.next_contact_at == clock.now() + timedelta(days=5)


@pytest.mark.asyncio
async def test_execute_deliver_failure_marks_turn_failed() -> None:
    clock = FakeClock()
    schedules = InMemoryRecontactScheduleStore()
    vips = InMemoryVipStore()
    vip = await _seed_vip(vips)
    past = clock.now() - timedelta(hours=1)
    await schedules.upsert_pending(vip.id, past, past)
    behavior = FakeBehavior(success=False)
    svc, deps = _make_service(
        schedules=schedules,
        vips=vips,
        behavior=behavior,
        clock=clock,
        route_resolver=FakeRouteResolver({vip.id: (9, "bc")}),
        ams=_ams(feature=True, global_mode="autonomous", vip_store=vips),
    )
    status = await svc.execute_recontact(vip.id)
    assert status == "failed"
    assert len(behavior.deliver_calls) == 1
    _, _, turn_id = behavior.deliver_calls[0]
    turn = await deps["turns"].get(turn_id)
    assert turn is not None
    assert turn.status == "failed"
    # schedule remains pending (or pushed — leave pending per A5 failure path)
    pending = await schedules.get_pending_by_vip(vip.id)
    assert pending is not None


@pytest.mark.asyncio
async def test_recontact_service_source_has_no_cognitive_pipeline_imports() -> None:
    from pathlib import Path

    import diana.application.recontact_service as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    forbidden = (
        "diana.cognitive.analyst",
        "diana.cognitive.planner",
        "diana.cognitive.generator",
        "diana.cognitive.director",
        "diana.llm",
    )
    for token in forbidden:
        assert token not in src, f"forbidden import surface: {token}"


@pytest.mark.asyncio
async def test_route_resolver_uses_open_including_claimed() -> None:
    """R1: ApprovalsDeliveriesRouteResolver resolves VIP route from claimed too."""
    from diana.application.recontact_service import ApprovalsDeliveriesRouteResolver
    from diana.application.memory import InMemoryPendingDeliveryStore

    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    vip_id = uuid4()
    turn_id = uuid4()
    await approvals.create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn_id,
            chat_id=42,
            business_connection_id="bc-claimed",
            draft_text="x",
            status="waiting",
            vip_id=vip_id,
        )
    )
    await approvals.claim_waiting(turn_id)
    resolver = ApprovalsDeliveriesRouteResolver(approvals, deliveries)
    route = await resolver.resolve(vip_id)
    assert route == (42, "bc-claimed")
