"""Destacar / Reprender owner UI — reprimand text delivers immediately."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

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
from diana.telegram.handlers.admin import handle_admin_text
from diana.telegram.handlers.callbacks import (
    CorrectSessionStore,
    dispatch_owner_callback,
)
from diana.telegram.keyboards import encode_callback
from tests.unit.application.test_admin_service import (
    OWNER_ID,
    _FakeTrustBudgetAdmin,
    _real_staging,
)
from tests.unit.application.test_admin_quality_feedback import _pending_vip_draft

OWNER = OWNER_ID


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


def _graph(*, feature_on: bool = True, staging=None, trust=None) -> dict:
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
        staging=staging,
        trust_budget=trust,
        feature_quality_feedback_enabled=feature_on,
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "actuator": actuator,
        "sessions": CorrectSessionStore(),
        "staging": staging,
        "trust": trust,
    }


async def _queue_draft(g: dict, *, vip_id=None, channel_type: str = "vip") -> object:
    turn = await g["coordinator"].begin_turn(
        chat_id=42, trigger_message_id=7, vip_id=vip_id, channel_type=channel_type
    )
    decision = Decision(
        action="approve",
        reason="ok",
        evaluation=_eval(),
        draft_text="hola VIP",
    )
    await g["admin"].send_draft_for_approval(
        IncomingTurn(
            turn_id=turn.id,
            chat_id=42,
            text="vip",
            business_connection_id="bc-1",
            telegram_message_id=7,
            vip_id=vip_id,
            channel_type=channel_type,
        ),
        decision,
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    return turn


async def _dispatch(g: dict, action: str, turn_id, data: str | None = None) -> str:
    return await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=data or encode_callback(action, turn_id),
        actor_id=OWNER,
    )


@pytest.mark.asyncio
async def test_reprimand_starts_session_when_flag_on_vip() -> None:
    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    status = await _dispatch(g, "reprimand", turn.id)
    assert status == "awaiting_reprimand"
    sess = g["sessions"].get_session(OWNER)
    assert sess is not None
    assert sess.mode == "reprimand"


@pytest.mark.asyncio
async def test_reprimand_noop_when_not_pending() -> None:
    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    await g["approvals"].mark_status(turn.id, "cancelled")
    status = await _dispatch(g, "reprimand", turn.id)
    assert status != "awaiting_reprimand"
    assert g["sessions"].get(OWNER) is None


@pytest.mark.asyncio
async def test_reprimand_flag_off_disables_without_start() -> None:
    g = _graph(feature_on=False)
    turn = await _queue_draft(g, vip_id=uuid4())
    status = await _dispatch(g, "reprimand", turn.id)
    assert status == "quality_feedback_disabled"
    assert g["sessions"].get(OWNER) is None


@pytest.mark.asyncio
async def test_reprimand_atencion_not_vip() -> None:
    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=None, channel_type="atencion")
    status = await _dispatch(g, "reprimand", turn.id)
    assert status == "quality_feedback_not_vip"
    assert g["sessions"].get(OWNER) is None


@pytest.mark.asyncio
async def test_reprimand_text_delivers_once_and_keeps_combo_session() -> None:
    from diana.application.memory import InMemoryVipStore

    staging, _ = _real_staging()
    save_spy = AsyncMock(wraps=staging.save_correction)
    staging.save_correction = save_spy  # type: ignore[method-assign]
    trust = _FakeTrustBudgetAdmin()
    g, turn, staging, _ = await _pending_vip_draft(
        staging=staging, trust_budget=trust, vip_id=uuid4()
    )
    sessions = CorrectSessionStore()
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=encode_callback("reprimand", turn.id),
        actor_id=OWNER,
    )
    assert status == "awaiting_reprimand"
    token = await handle_admin_text(
        text="texto corregido ya",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=sessions,
    )
    assert token == "awaiting_reprimand_combo"
    assert save_spy.await_count == 1
    assert trust.correction_calls == [turn.id]
    assert g["actuator"].send_count() >= 1
    assert g["actuator"].calls[-1]["text"] == "texto corregido ya"
    assert sessions.get(OWNER) == turn.id
    sess = sessions.get_session(OWNER)
    assert sess is not None and sess.candidate_id is not None

    token2 = await handle_admin_text(
        text="otro texto no debe reenviar",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=sessions,
    )
    assert token2 == "reprimand_combo_use_buttons"
    assert save_spy.await_count == 1
    assert trust.correction_calls == [turn.id]
    assert g["actuator"].send_count() == 1


@pytest.mark.asyncio
async def test_classic_correct_still_clears_session() -> None:
    from diana.application.memory import InMemoryVipStore

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    status = await _dispatch(g, "correct", turn.id)
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
    assert g["sessions"].get(OWNER) is None


@pytest.mark.asyncio
async def test_reprimand_no_combo_when_candidate_not_persisted() -> None:
    from diana.application.memory import InMemoryVipStore

    staging, _ = _real_staging()
    staging.save_correction = AsyncMock(return_value=None)  # type: ignore[method-assign]
    g, turn, _, _ = await _pending_vip_draft(staging=staging, vip_id=uuid4())
    sessions = CorrectSessionStore()
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=encode_callback("reprimand", turn.id),
        actor_id=OWNER,
    )
    token = await handle_admin_text(
        text="sandbox delivery only",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=sessions,
    )
    assert token == "reprimand_lesson_not_saved"
    assert sessions.get(OWNER) is None
    assert g["actuator"].send_count() >= 1


@pytest.mark.asyncio
async def test_reprimand_stale_when_correct_cancelled() -> None:
    from diana.application.memory import InMemoryVipStore

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("reprimand", turn.id),
        actor_id=OWNER,
    )
    await g["coordinator"].begin_turn(chat_id=42)
    token = await handle_admin_text(
        text="too late",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert token == "stale"
    assert g["sessions"].get(OWNER) is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_expired_combo_text_is_lesson_not_saved() -> None:
    from diana.application.memory import InMemoryVipStore

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock_box = {"t": now}

    def clock() -> datetime:
        return clock_box["t"]

    sessions = CorrectSessionStore(ttl=timedelta(minutes=15), clock=clock)
    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    sessions.start(OWNER, turn.id, mode="reprimand", chat_id=42)
    sessions.capture_reprimand(OWNER, candidate_id=uuid4(), corrected_text="x")
    clock_box["t"] = now + timedelta(minutes=16)
    token = await handle_admin_text(
        text="late combo",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=sessions,
    )
    assert token == "reprimand_lesson_not_saved"
    assert token != "session_expired"
