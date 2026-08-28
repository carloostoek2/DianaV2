"""Owner callbacks — approve delivers; non-owner denied; no VIP auto-send."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

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
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn
from diana.telegram.handlers.callbacks import (
    CorrectSessionStore,
    dispatch_owner_callback,
)
from diana.telegram.keyboards import (
    encode_callback,
    encode_severity,
    parse_severity,
)

OWNER = 999001
OTHER = 111


def _eval() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.9,
        doctrine=0.9,
        consistency=0.9,
        safety=0.95,
        coverage=0.9,
        empathy=0.9,
    )


@pytest.fixture
def graph() -> dict:
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
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "actuator": actuator,
        "sessions": CorrectSessionStore(),
    }


async def _queue_draft(g: dict, draft: str = "hola VIP"):
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text=draft,
    )
    await g["admin"].send_draft_for_approval(
        IncomingTurn(
            turn_id=turn.id,
            chat_id=42,
            text="vip",
            business_connection_id="bc-1",
            telegram_message_id=7,
        ),
        decision,
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    return turn


@pytest.mark.asyncio
async def test_approve_callback_delivers(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OWNER,
    )
    assert status == "approved"
    assert g["actuator"].send_count() >= 1


@pytest.mark.asyncio
async def test_without_approve_no_send(graph: dict) -> None:
    g = graph
    await _queue_draft(g)
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_non_owner_callback_forbidden(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OTHER,
    )
    assert status == "forbidden"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_escalate_callback_no_deliver(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("escalate", turn.id),
        actor_id=OWNER,
    )
    assert status == "escalated"
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "escalated"


@pytest.mark.asyncio
async def test_correct_callback_starts_session_no_deliver(graph: dict) -> None:
    """Correct button only opens FSM; deliver happens later via handle_correct."""
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert status == "awaiting_correct"
    assert g["sessions"].get(OWNER) == turn.id
    assert g["actuator"].send_count() == 0
    # waiting approval still open until free-text correct
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.status == "waiting"


@pytest.mark.asyncio
async def test_correct_starts_session_with_moderate_prefill(graph: dict) -> None:
    """SPEC-EA-07: with no signals wired the deterministic prefill is moderate."""
    g = graph
    turn = await _queue_draft(g)
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    sess = g["sessions"].get_session(OWNER)
    assert sess is not None
    assert sess.severity == "moderate"


@pytest.mark.asyncio
async def test_correct_prefill_major_when_gray_zone_open(graph: dict) -> None:
    """SPEC-EA-07 (Señal C): an open gray-zone query → prefill major."""
    from types import SimpleNamespace

    g = graph
    turn = await _queue_draft(g)

    async def _open_query(t):
        return SimpleNamespace(id=t)

    gray_zone = SimpleNamespace(get_open_query_by_turn_id=_open_query)
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
        gray_zone=gray_zone,
    )
    sess = g["sessions"].get_session(OWNER)
    assert sess is not None
    assert sess.severity == "major"


@pytest.mark.asyncio
async def test_correct_router_sends_severity_picker_with_moderate_default(
    graph: dict,
) -> None:
    """SPEC-EA-07 (Fase 4, happy-path): the router pre-selects moderate and
    sends the severity picker message with the 3-button sv: keyboard (default
    case — no gray-zone / doctrine / hard-gate signal wired)."""
    from aiogram.types import CallbackQuery, Chat, Message, User
    from unittest.mock import Mock

    from diana.telegram.handlers.callbacks import build_callback_router

    g = graph
    turn = await _queue_draft(g)
    sessions = Mock(spec=CorrectSessionStore)
    router = build_callback_router(
        admin=g["admin"],
        correct_sessions=sessions,
        owner_telegram_id=OWNER,
    )
    on_callback = router.callback_query.handlers[0].callback

    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="draft",
    )
    answer = AsyncMock(return_value=True)
    object.__setattr__(msg, "answer", answer)
    query = CallbackQuery(
        id="cq-correct",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_callback("correct", turn.id),
        message=msg,
    )
    object.__setattr__(query, "answer", AsyncMock(return_value=True))

    await on_callback(query)

    # Prefill path (default case): the session is started with moderate.
    sessions.start.assert_called_once_with(OWNER, turn.id, severity="moderate")

    # Picker send: exactly one message.answer carries the severity keyboard.
    picker_calls = [
        c for c in answer.call_args_list if c.kwargs.get("reply_markup") is not None
    ]
    assert len(picker_calls) == 1
    args, kwargs = picker_calls[0]
    assert args == ("Gravedad de la corrección:",)
    kb = kwargs["reply_markup"]
    assert len(kb.inline_keyboard) == 1
    row = kb.inline_keyboard[0]
    assert len(row) == 3
    assert all(btn.callback_data.startswith("sv:") for btn in row)


@pytest.mark.asyncio
async def test_severity_callback_sets_session_severity(graph: dict) -> None:
    """SPEC-EA-07 (sv:): tapping a severity button mutates the session in-place."""
    g = graph
    turn = await _queue_draft(g)
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert g["sessions"].get_session(OWNER).severity == "moderate"  # noqa: SLF001

    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_severity(turn.id, "major"),
        actor_id=OWNER,
    )

    assert status == "severity_set"
    assert g["sessions"].get_session(OWNER).severity == "major"


@pytest.mark.asyncio
async def test_severity_callback_expired_session_is_noop(graph: dict) -> None:
    """SPEC-EA-07: sv: without a live session → no-op (expired/never started)."""
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_severity(turn.id, "minor"),
        actor_id=OWNER,
    )
    assert status == "severity_session_expired"
    assert g["sessions"].get_session(OWNER) is None


@pytest.mark.asyncio
async def test_severity_callback_stale_turn_does_not_mutate(graph: dict) -> None:
    """SPEC-EA-07 (review round 1): an sv: button from an OLD turn must not label
    the live session of a NEWER turn (turn-ownership guard)."""
    g = graph
    turn_a = await _queue_draft(g)
    turn_b = await _queue_draft(g)
    # Active session belongs to turn B.
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn_b.id),
        actor_id=OWNER,
    )
    assert g["sessions"].get_session(OWNER).turn_id == turn_b.id

    # A stale sv: button from turn A taps while turn B session is live.
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_severity(turn_a.id, "major"),
        actor_id=OWNER,
    )

    assert status == "severity_stale"
    sess = g["sessions"].get_session(OWNER)
    assert sess is not None
    assert sess.turn_id == turn_b.id
    assert sess.severity == "moderate"  # NOT mutated to major by the stale tap

    # The same-turn happy path still applies the chosen severity.
    status_ok = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_severity(turn_b.id, "major"),
        actor_id=OWNER,
    )
    assert status_ok == "severity_set"
    assert g["sessions"].get_session(OWNER).severity == "major"


@pytest.mark.asyncio
async def test_correct_callback_non_owner_forbidden(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OTHER,
    )
    assert status == "forbidden"
    assert g["sessions"].get(OTHER) is None
    assert g["sessions"].get(OWNER) is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_approve_after_supersede_returns_stale_replaced(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    await g["coordinator"].begin_turn(chat_id=42)  # supersede
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OWNER,
    )
    assert status == "stale_replaced"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_approve_cancelled_approval_returns_stale_cancelled(graph: dict) -> None:
    g = graph
    turn = await _queue_draft(g)
    await g["approvals"].mark_status(turn.id, "cancelled")
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OWNER,
    )
    assert status == "stale_cancelled"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_correct_free_text_delivers(graph: dict) -> None:
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    g = graph
    turn = await _queue_draft(g, draft="original")
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert status == "awaiting_correct"
    result = await handle_admin_text(
        text="corrected with encuentro word ok",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert result == "corrected"
    assert g["actuator"].send_count() >= 1
    assert g["actuator"].calls[-1]["text"] == "corrected with encuentro word ok"
    assert g["sessions"].get(OWNER) is None


@pytest.mark.asyncio
async def test_correct_free_text_propagates_session_severity(graph: dict) -> None:
    """SPEC-EA-07 (Fase 3): the free-text correct handler forwards the session
    severity to AdminService.handle_correct (defaults to moderate otherwise)."""
    from types import SimpleNamespace

    from unittest.mock import AsyncMock

    from diana.application.memory import InMemoryVipStore
    from diana.telegram.handlers.admin import handle_admin_text

    g = graph
    turn = await _queue_draft(g, draft="original")
    g["sessions"].start(OWNER, turn.id, severity="major")

    spy = AsyncMock(return_value=SimpleNamespace(success=True, cancelled=False))
    g["admin"].handle_correct = spy  # type: ignore[method-assign]
    await handle_admin_text(
        text="corrected text",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    spy.assert_awaited_once()
    kwargs = spy.await_args.kwargs
    assert kwargs.get("severity") == "major"


@pytest.mark.asyncio
async def test_correct_free_text_defaults_severity_to_moderate(graph: dict) -> None:
    """SPEC-EA-07 (Fase 3): a session without severity falls back to moderate."""
    from types import SimpleNamespace

    from unittest.mock import AsyncMock

    from diana.application.memory import InMemoryVipStore
    from diana.telegram.handlers.admin import handle_admin_text

    g = graph
    turn = await _queue_draft(g, draft="original")
    g["sessions"].start(OWNER, turn.id)  # no severity set

    spy = AsyncMock(return_value=SimpleNamespace(success=True, cancelled=False))
    g["admin"].handle_correct = spy  # type: ignore[method-assign]
    await handle_admin_text(
        text="corrected text",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    spy.assert_awaited_once()
    kwargs = spy.await_args.kwargs
    assert kwargs.get("severity") == "moderate"


@pytest.mark.asyncio
async def test_correct_free_text_after_supersede_stale(graph: dict) -> None:
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    g = graph
    turn = await _queue_draft(g)
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert g["sessions"].get(OWNER) == turn.id
    await g["coordinator"].begin_turn(chat_id=42)  # supersede cancels approval
    g["sessions"].cancel_turn(turn.id)  # supersede invalidates correct FSM
    # Session cleared by cancel_turn; if still set, domain still no-ops honestly.
    g["sessions"].start(OWNER, turn.id)
    result = await handle_admin_text(
        text="too late",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert result == "stale"
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_correct_session_timeout(graph: dict) -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock_box = {"t": now}

    def clock() -> datetime:
        return clock_box["t"]

    sessions = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
    g = graph
    g["sessions"] = sessions
    turn = await _queue_draft(g)
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=encode_callback("correct", turn.id),
        actor_id=OWNER,
    )
    assert sessions.get(OWNER) == turn.id
    clock_box["t"] = now + timedelta(minutes=16)
    assert sessions.get(OWNER) is None


def test_correct_session_resolve_live_expired_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from datetime import UTC, datetime, timedelta
    import logging

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock_box = {"t": now}

    def clock() -> datetime:
        return clock_box["t"]

    sessions = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
    turn_id = uuid4()

    # never-started
    assert sessions.resolve(OWNER) == ("none", None)

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        sessions.start(OWNER, turn_id)
    assert any(
        r.getMessage() == "correct_session_started" for r in caplog.records
    )
    state, tid = sessions.resolve(OWNER)
    assert state == "live"
    assert tid == turn_id
    assert sessions.get(OWNER) == turn_id  # resolve live does not consume

    clock_box["t"] = now + timedelta(minutes=16)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        state, expired_id = sessions.resolve(OWNER)
    assert state == "expired"
    assert expired_id == turn_id
    assert sum(1 for r in caplog.records if r.getMessage() == "correct_session_expired") == 1
    # second resolve after expire consume
    assert sessions.resolve(OWNER) == ("none", None)
    assert sessions.get(OWNER) is None


@pytest.mark.asyncio
async def test_handle_admin_text_session_expired_after_ttl(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from datetime import UTC, datetime, timedelta
    import logging
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock_box = {"t": now}

    def clock() -> datetime:
        return clock_box["t"]

    sessions = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
    turn_id = uuid4()
    sessions.start(OWNER, turn_id)
    clock_box["t"] = now + timedelta(minutes=16)

    with caplog.at_level(logging.INFO, logger="diana.telegram"):
        result = await handle_admin_text(
            text="too late free text",
            actor_id=OWNER,
            owner_telegram_id=OWNER,
            vips=InMemoryVipStore(),
            admin=None,  # type: ignore[arg-type]
            correct_sessions=sessions,
        )
    assert result == "session_expired"
    assert sessions.get(OWNER) is None
    assert sum(1 for r in caplog.records if r.getMessage() == "correct_session_expired") == 1


@pytest.mark.asyncio
async def test_handle_admin_text_never_started_silent() -> None:
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    sessions = CorrectSessionStore()
    result = await handle_admin_text(
        text="private chatter",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=None,  # type: ignore[arg-type]
        correct_sessions=sessions,
    )
    assert result == "ignored"
    assert result != "session_expired"


@pytest.mark.asyncio
async def test_handle_admin_text_after_cancel_not_session_expired() -> None:
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.application.memory import InMemoryVipStore

    sessions = CorrectSessionStore()
    sessions.start(OWNER, uuid4())
    sessions.cancel(OWNER)
    result = await handle_admin_text(
        text="after cancel",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=None,  # type: ignore[arg-type]
        correct_sessions=sessions,
    )
    assert result == "ignored"


# --- Escalation DM actions (ver traza / falso positivo / responder) -----------


async def _escalated_turn(g: dict) -> UUID:
    """Mint an escalated turn on chat 42 (bc-1) with its escalation record."""
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["coordinator"].transition(turn.id, "escalated")
    await g["admin"]._escalations.create(  # noqa: SLF001
        turn.id, tipo="risk_high", motivo="risk", business_connection_id="bc-1"
    )
    return UUID(str(turn.id))


@pytest.mark.asyncio
async def test_escalation_fp_callback_marks_false_positive(graph: dict) -> None:
    from diana.application.owner_marks import InMemoryOwnerMarkStore
    from diana.telegram.keyboards import encode_escalation_callback

    g = graph
    turn_id = await _escalated_turn(g)
    marks = InMemoryOwnerMarkStore()
    g["admin"]._fp_marks = marks  # noqa: SLF001
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_escalation_callback("fp", turn_id),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert status == "escalation_fp_marked"
    assert await marks.count_in_range(date(2000, 1, 1), date(2100, 1, 1)) == 1


@pytest.mark.asyncio
async def test_escalation_trace_callback_views_trace(graph: dict) -> None:
    from types import SimpleNamespace

    from diana.telegram.keyboards import encode_escalation_callback

    g = graph
    turn_id = await _escalated_turn(g)
    fake_trace = SimpleNamespace(get_full_trace=AsyncMock(return_value=object()))
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_escalation_callback("trace", turn_id),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        admin_trace=fake_trace,  # type: ignore[arg-type]
    )
    assert status == "escalation_trace_view"


@pytest.mark.asyncio
async def test_escalation_reply_callback_starts_session(graph: dict) -> None:
    from diana.telegram.keyboards import encode_escalation_callback

    g = graph
    turn_id = await _escalated_turn(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_escalation_callback("reply", turn_id),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    assert status == "escalation_reply_prompted"
    sess = g["sessions"].get_session(OWNER)
    assert sess is not None and sess.mode == "escalation_reply"
    assert sess.turn_id == turn_id


@pytest.mark.asyncio
async def test_escalation_reply_text_delivers_to_chat(graph: dict) -> None:
    from diana.application.memory import InMemoryVipStore
    from diana.telegram.handlers.admin import handle_admin_text
    from diana.telegram.keyboards import encode_escalation_callback

    g = graph
    turn_id = await _escalated_turn(g)
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_escalation_callback("reply", turn_id),
        actor_id=OWNER,
        owner_telegram_id=OWNER,
    )
    result = await handle_admin_text(
        text="tienes razón, te espero mañana",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert result == "escalation_reply_sent"
    sends = [c for c in g["actuator"].calls if c["op"] == "send_message"]
    assert any(
        c["chat_id"] == 42 and c["text"] == "tienes razón, te espero mañana"
        for c in sends
    )
    assert g["sessions"].get_session(OWNER) is None


@pytest.mark.asyncio
async def test_escalation_callback_non_owner_forbidden(graph: dict) -> None:
    from diana.telegram.keyboards import encode_escalation_callback

    g = graph
    turn_id = await _escalated_turn(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_escalation_callback("fp", turn_id),
        actor_id=OTHER,
        owner_telegram_id=OWNER,
    )
    assert status == "forbidden"
