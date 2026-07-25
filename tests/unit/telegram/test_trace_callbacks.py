"""Unit tests for trace callback dispatch (dispatch_owner_callback)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from diana.application.admin_service import AdminService
from diana.application.admin_trace_service import AdminTraceService
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
from diana.telegram.handlers.callbacks import CorrectSessionStore, dispatch_owner_callback
from diana.telegram.keyboards import encode_trace_detail, encode_trace_json, encode_trace_page, encode_trace_view


class FakeTraceabilityReader:
    """Minimal TraceabilityReader fake for callback tests."""

    def __init__(self) -> None:
        self._traces: dict[str, dict] = {}

    def seed_trace(self, turn_id, data: dict) -> None:
        self._traces[str(turn_id)] = dict(data)

    async def get_recent_turns(self, limit: int = 10, offset: int = 0, chat_id: int | None = None) -> list[dict]:
        return []

    async def get_full_trace(self, turn_id) -> dict | None:
        return self._traces.get(str(turn_id))

    async def count_recent(self, chat_id: int | None = None) -> int:
        return 0


OWNER = 999001


@pytest.fixture
def admin_trace() -> AdminTraceService:
    return AdminTraceService(traces=FakeTraceabilityReader(), trace_ttl_days=30)


@pytest.fixture
def standard_admin() -> AdminService:
    """Minimal AdminService for standard callback tests."""
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
    )
    coordinator = TurnCoordinator(turns, approvals, behavior)
    return AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER,
    )


class TestTraceViewCallback:
    async def test_vt_returns_trace_view_token(self, admin_trace: AdminTraceService) -> None:
        turn_id = uuid4()
        reader: FakeTraceabilityReader = admin_trace._traces  # type: ignore[attr-defined]  # noqa: SLF001
        reader.seed_trace(str(turn_id), {
            "turn_id": turn_id, "chat_id": 1, "status": "delivered", "error": None,
            "vip_id": None, "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
            "comprehension": None, "plan": None, "retrieved": None,
            "prompt_text": None, "generated_text": "Hello",
            "evaluation": None, "decision": {"action": "approve"},
            "delivery_result": None, "timings": {"total_ms": 100},
        })
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_view(turn_id),
            actor_id=OWNER,
            admin_trace=admin_trace,
        )
        assert status == "trace_view"

    async def test_vt_trace_not_found(self, admin_trace: AdminTraceService) -> None:
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_view(uuid4()),
            actor_id=OWNER,
            admin_trace=admin_trace,
        )
        assert status == "trace_not_found"


class TestTraceDetailCallback:
    async def test_td_returns_detail_token(self, admin_trace: AdminTraceService) -> None:
        turn_id = uuid4()
        reader: FakeTraceabilityReader = admin_trace._traces  # type: ignore[attr-defined]  # noqa: SLF001
        reader.seed_trace(str(turn_id), {
            "turn_id": turn_id, "chat_id": 1, "status": "delivered", "error": None,
            "vip_id": None, "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
            "comprehension": {"intent": "chat"}, "plan": None, "retrieved": None,
            "prompt_text": None, "generated_text": "Hello",
            "evaluation": None, "decision": {"action": "approve"},
            "delivery_result": None, "timings": {"analyst_ms": 100},
        })
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_detail(turn_id, "analyst"),
            actor_id=OWNER,
            admin_trace=admin_trace,
        )
        assert status == "trace_detail_view"

    async def test_td_not_found(self, admin_trace: AdminTraceService) -> None:
        turn_id = uuid4()
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_detail(turn_id, "analyst"),
            actor_id=OWNER,
            admin_trace=admin_trace,
        )
        assert status == "trace_not_found"


class TestTracePageCallback:
    async def test_tp_returns_page_token(self, admin_trace: AdminTraceService) -> None:
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_page(1),
            actor_id=OWNER,
            admin_trace=admin_trace,
        )
        assert status == "trace_page"

    async def test_tp_page_zero(self, admin_trace: AdminTraceService) -> None:
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_page(0),
            actor_id=OWNER,
            admin_trace=admin_trace,
        )
        assert status == "trace_page"


class TestTraceJsonCallback:
    async def test_tj_returns_export_token(self, admin_trace: AdminTraceService) -> None:
        turn_id = uuid4()
        reader: FakeTraceabilityReader = admin_trace._traces  # type: ignore[attr-defined]  # noqa: SLF001
        reader.seed_trace(str(turn_id), {
            "turn_id": turn_id, "chat_id": 1, "status": "delivered", "error": None,
            "vip_id": None, "created_at": datetime(2026, 7, 25, 14, 30, tzinfo=UTC),
            "comprehension": None, "plan": None, "retrieved": None,
            "prompt_text": None, "generated_text": "Hello",
            "evaluation": None, "decision": {"action": "approve"},
            "delivery_result": None, "timings": {},
        })
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_json(turn_id),
            actor_id=OWNER,
            admin_trace=admin_trace,
        )
        assert status == "trace_export"


class TestBackwardCompat:
    """Existing standard callbacks still work with admin_trace present."""

    async def test_no_admin_trace_returns_ignored_for_trace_callbacks(self) -> None:
        """When admin_trace is None, trace callbacks return 'ignored'."""
        turn_id = uuid4()
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_view(turn_id),
            actor_id=OWNER,
            admin_trace=None,
        )
        assert status == "ignored"

    async def test_td_no_admin_trace_returns_ignored(self) -> None:
        turn_id = uuid4()
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_detail(turn_id, "analyst"),
            actor_id=OWNER,
            admin_trace=None,
        )
        assert status == "ignored"

    async def test_tp_no_admin_trace_returns_ignored(self) -> None:
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_page(1),
            actor_id=OWNER,
            admin_trace=None,
        )
        assert status == "ignored"

    async def test_tj_no_admin_trace_returns_ignored(self) -> None:
        turn_id = uuid4()
        status = await dispatch_owner_callback(
            admin=None,  # type: ignore[arg-type]
            correct_sessions=CorrectSessionStore(),
            callback_data=encode_trace_json(turn_id),
            actor_id=OWNER,
            admin_trace=None,
        )
        assert status == "ignored"

    async def test_standard_callbacks_work_with_admin_trace(
        self, standard_admin: AdminService
    ) -> None:
        """Standard callback prefixes (a:, c:, e:) still work when admin_trace is present."""
        turn_id = uuid4()
        # Standard callbacks without an active turn return forbidden
        # because admin._assert_owner check fails when admin=None.
        # With a real admin that has owner_telegram_id set, missing actor
        # returns forbidden.
        status = await dispatch_owner_callback(
            admin=standard_admin,
            correct_sessions=CorrectSessionStore(),
            callback_data="a:" + str(uuid4()),
            actor_id=OWNER,
            admin_trace=AdminTraceService(traces=FakeTraceabilityReader(), trace_ttl_days=30),
        )
        # A valid non-stale turn returns "approved"; stale turn returns None.
        # Without a seeded turn, it should be forbidden or stale.
        assert status in ("stale", "forbidden", "approved")
