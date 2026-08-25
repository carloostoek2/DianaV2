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


@pytest.mark.asyncio
async def test_gd_does_not_write_gold_or_approve() -> None:
    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    gold = AsyncMock(wraps=g["admin"].handle_mark_gold)
    approve = AsyncMock(wraps=g["admin"].handle_approve)
    g["admin"].handle_mark_gold = gold  # type: ignore[method-assign]
    g["admin"].handle_approve = approve  # type: ignore[method-assign]
    status = await _dispatch(g, "gold", turn.id)
    assert status == "awaiting_gold_scope"
    gold.assert_not_awaited()
    approve.assert_not_awaited()


@pytest.mark.asyncio
async def test_gdc_global_marks_gold_once() -> None:
    from diana.telegram.keyboards import encode_gold_confirm

    staging, _ = _real_staging()
    g, turn, _, _ = await _pending_vip_draft(staging=staging, vip_id=uuid4())
    gold = AsyncMock(wraps=g["admin"].handle_mark_gold)
    g["admin"].handle_mark_gold = gold  # type: ignore[method-assign]
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=CorrectSessionStore(),
        callback_data=encode_gold_confirm(turn.id, "g"),
        actor_id=OWNER,
    )
    assert status == "gold_marked"
    gold.assert_awaited_once()
    assert gold.await_args.kwargs["scope"] == "global"
    assert g["actuator"].send_count() >= 1


@pytest.mark.asyncio
async def test_gdc_vip_scope() -> None:
    from diana.telegram.keyboards import encode_gold_confirm

    staging, _ = _real_staging()
    vid = uuid4()
    g, turn, _, _ = await _pending_vip_draft(staging=staging, vip_id=vid)
    gold = AsyncMock(wraps=g["admin"].handle_mark_gold)
    g["admin"].handle_mark_gold = gold  # type: ignore[method-assign]
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=CorrectSessionStore(),
        callback_data=encode_gold_confirm(turn.id, "v"),
        actor_id=OWNER,
    )
    assert status == "gold_marked"
    assert gold.await_args.kwargs["scope"] == "vip"


@pytest.mark.asyncio
async def test_gdc_forwards_delivery_progress_to_mark_gold() -> None:
    """Gold confirm wires the live delivery progress callback like approve."""
    from diana.telegram.keyboards import encode_gold_confirm

    staging, _ = _real_staging()
    g, turn, _, _ = await _pending_vip_draft(staging=staging, vip_id=uuid4())
    gold = AsyncMock(wraps=g["admin"].handle_mark_gold)
    g["admin"].handle_mark_gold = gold  # type: ignore[method-assign]

    async def progress(event: object) -> None:
        pass

    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=CorrectSessionStore(),
        callback_data=encode_gold_confirm(turn.id, "g"),
        actor_id=OWNER,
        on_delivery_progress=progress,
    )
    assert status == "gold_marked"
    gold.assert_awaited_once()
    assert gold.await_args.kwargs["on_progress"] is progress


@pytest.mark.asyncio
async def test_gdc_cancel_restores_without_writes() -> None:
    from diana.telegram.keyboards import encode_gold_confirm

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    gold = AsyncMock(wraps=g["admin"].handle_mark_gold)
    approve = AsyncMock(wraps=g["admin"].handle_approve)
    g["admin"].handle_mark_gold = gold  # type: ignore[method-assign]
    g["admin"].handle_approve = approve  # type: ignore[method-assign]
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_gold_confirm(turn.id, "x"),
        actor_id=OWNER,
    )
    assert status == "gold_scope_cancel"
    gold.assert_not_awaited()
    approve.assert_not_awaited()


@pytest.mark.asyncio
async def test_flag_off_quality_buttons_toast_no_writes() -> None:
    from diana.telegram.keyboards import encode_gold_confirm, encode_reprimand_confirm

    g = _graph(feature_on=False)
    turn = await _queue_draft(g, vip_id=uuid4())
    gold = AsyncMock(wraps=g["admin"].handle_mark_gold)
    reprimand = AsyncMock(wraps=g["admin"].handle_reprimand)
    g["admin"].handle_mark_gold = gold  # type: ignore[method-assign]
    g["admin"].handle_reprimand = reprimand  # type: ignore[method-assign]
    sessions = g["sessions"]
    sessions.start(OWNER, turn.id, mode="reprimand", chat_id=42)
    sessions.capture_reprimand(OWNER, candidate_id=uuid4(), corrected_text="x")
    for data in (
        encode_callback("gold", turn.id),
        encode_gold_confirm(turn.id, "g"),
        encode_reprimand_confirm(turn.id, "ex", "g"),
    ):
        status = await dispatch_owner_callback(
            admin=g["admin"],
            correct_sessions=sessions,
            callback_data=data,
            actor_id=OWNER,
        )
        assert status == "quality_feedback_disabled"
    gold.assert_not_awaited()
    reprimand.assert_not_awaited()


@pytest.mark.asyncio
async def test_atencion_forced_quality_buttons_not_vip() -> None:
    from diana.telegram.keyboards import encode_reprimand_confirm

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=None, channel_type="atencion")
    assert await _dispatch(g, "gold", turn.id) == "quality_feedback_not_vip"
    assert (
        await dispatch_owner_callback(
            admin=g["admin"],
            correct_sessions=g["sessions"],
            callback_data=encode_reprimand_confirm(turn.id, "pol", "g"),
            actor_id=OWNER,
        )
        == "quality_feedback_not_vip"
    )


@pytest.mark.asyncio
async def test_rpc_promotes_only_after_reprimand_text() -> None:
    from diana.application.memory import InMemoryVipStore
    from diana.telegram.keyboards import encode_reprimand_confirm

    staging, repo = _real_staging()
    save_spy = AsyncMock(wraps=staging.save_correction)
    staging.save_correction = save_spy  # type: ignore[method-assign]
    trust = _FakeTrustBudgetAdmin()
    g, turn, staging, repo = await _pending_vip_draft(
        staging=staging, trust_budget=trust, vip_id=uuid4()
    )
    sessions = CorrectSessionStore()
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=encode_callback("reprimand", turn.id),
        actor_id=OWNER,
    )
    await handle_admin_text(
        text="fixed now",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=sessions,
    )
    sess = sessions.get_session(OWNER)
    assert sess is not None and sess.candidate_id is not None
    candidate_id = sess.candidate_id
    repo.get_by_id.return_value = type(repo.get_by_id.return_value)(
        id=candidate_id,
        status="pending",
        candidate_type="example",
        payload={
            "original_draft": "original draft",
            "corrected_text": "fixed now",
            "context": {"turn_text": "vip trigger text"},
            "channel_type": "vip",
        },
    )
    reprimand = AsyncMock(wraps=g["admin"].handle_reprimand)
    g["admin"].handle_reprimand = reprimand  # type: ignore[method-assign]
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=encode_reprimand_confirm(turn.id, "ex", "g"),
        actor_id=OWNER,
    )
    assert status == "reprimand_promoted"
    assert save_spy.await_count == 1
    assert trust.correction_calls == [turn.id]
    reprimand.assert_awaited_once()
    assert reprimand.await_args.kwargs["candidate_id"] == candidate_id
    assert reprimand.await_args.kwargs["mode"] == "counter_example"
    assert reprimand.await_args.kwargs["scope"] == "global"


@pytest.mark.asyncio
async def test_rpc_without_session_does_not_use_approve_noop() -> None:
    from diana.telegram.keyboards import encode_reprimand_confirm

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    noop = AsyncMock(wraps=g["admin"].classify_approve_noop)
    g["admin"].classify_approve_noop = noop  # type: ignore[method-assign]
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_reprimand_confirm(turn.id, "ex", "g"),
        actor_id=OWNER,
    )
    assert status == "reprimand_lesson_not_saved"
    noop.assert_not_awaited()


@pytest.mark.asyncio
async def test_rpc_double_tap_already_saved() -> None:
    from diana.telegram.keyboards import encode_reprimand_confirm

    staging, repo = _real_staging()
    g, turn, staging, repo = await _pending_vip_draft(
        staging=staging, vip_id=uuid4()
    )
    candidate_id = uuid4()
    pending = repo.get_by_id.return_value
    pending.id = candidate_id
    pending.status = "pending"

    async def _update(_cid, status):
        pending.status = status
        return True

    repo.update_status = AsyncMock(side_effect=_update)
    sessions = CorrectSessionStore()
    sessions.start(OWNER, turn.id, mode="reprimand", chat_id=42)
    sessions.capture_reprimand(
        OWNER, candidate_id=candidate_id, corrected_text="fixed"
    )
    data = encode_reprimand_confirm(turn.id, "ex", "g")
    first = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=data,
        actor_id=OWNER,
    )
    assert first == "reprimand_promoted"
    sessions.start(OWNER, turn.id, mode="reprimand", chat_id=42)
    sessions.capture_reprimand(
        OWNER, candidate_id=candidate_id, corrected_text="fixed"
    )
    second = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=data,
        actor_id=OWNER,
    )
    assert second == "reprimand_already_saved"


@pytest.mark.asyncio
async def test_rpc_quality_disabled_exception_toasts() -> None:
    from diana.application.admin_service import QualityFeedbackDisabled
    from diana.telegram.keyboards import encode_reprimand_confirm

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    g["sessions"].start(OWNER, turn.id, mode="reprimand", chat_id=42)
    g["sessions"].capture_reprimand(
        OWNER, candidate_id=uuid4(), corrected_text="x"
    )
    g["admin"].handle_reprimand = AsyncMock(  # type: ignore[method-assign]
        side_effect=QualityFeedbackDisabled("FEATURE_QUALITY_FEEDBACK_ENABLED is off")
    )
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_reprimand_confirm(turn.id, "pol", "v"),
        actor_id=OWNER,
    )
    assert status == "quality_feedback_disabled"


@pytest.mark.asyncio
async def test_send_draft_sets_quality_flag_only_for_vip() -> None:
    g_vip, _, _, _ = await _pending_vip_draft(feature_on=True, vip_id=uuid4())
    assert g_vip["notifier"].drafts[-1].show_quality_feedback is True
    g_atn, _, _, _ = await _pending_vip_draft(
        feature_on=True, vip_id=None, channel_type="atencion"
    )
    assert g_atn["notifier"].drafts[-1].show_quality_feedback is False
    g_off, _, _, _ = await _pending_vip_draft(feature_on=False, vip_id=uuid4())
    assert g_off["notifier"].drafts[-1].show_quality_feedback is False


@pytest.mark.asyncio
async def test_tb_rebuilds_quality_row_when_flag_and_vip() -> None:
    from unittest.mock import MagicMock

    from aiogram.types import CallbackQuery, Chat, Message, User

    from diana.telegram.handlers.callbacks import build_callback_router
    from diana.telegram.keyboards import encode_trace_back_to_draft

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    router = build_callback_router(
        admin=g["admin"],
        owner_telegram_id=OWNER,
        admin_trace=MagicMock(),
    )
    on_cb = router.callback_query.handlers[0].callback
    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="draft",
    )
    object.__setattr__(msg, "edit_text", AsyncMock(return_value=True))
    query = CallbackQuery(
        id="cq-tb",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_trace_back_to_draft(turn.id),
        message=msg,
    )
    object.__setattr__(query, "answer", AsyncMock(return_value=True))
    await on_cb(query)
    kb = msg.edit_text.await_args.kwargs["reply_markup"]
    cbs = [b.callback_data or "" for row in kb.inline_keyboard for b in row]
    assert any(cb.startswith("gd:") for cb in cbs)


@pytest.mark.asyncio
async def test_inbound_cancels_combo_before_rpc() -> None:
    from aiogram.types import Chat, Message, User

    from diana.telegram.handlers.business import build_business_router
    from diana.telegram.keyboards import encode_reprimand_confirm

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    g["sessions"].start(OWNER, turn.id, mode="reprimand", chat_id=42)
    g["sessions"].capture_reprimand(
        OWNER, candidate_id=uuid4(), corrected_text="x"
    )
    orch = AsyncMock()
    orch.handle_vip_message = AsyncMock(return_value=uuid4())
    router = build_business_router(
        orchestrator=orch, on_vip_inbound=g["sessions"].cancel_combo_for_chat
    )
    on_business = router.business_message.handlers[0].callback
    msg = Message(
        message_id=7,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=User(id=111, is_bot=False, first_name="Vip"),
        text="nuevo",
        business_connection_id="bc-1",
    )
    await on_business(msg)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_reprimand_confirm(turn.id, "ex", "g"),
        actor_id=OWNER,
    )
    assert status == "reprimand_lesson_not_saved"


@pytest.mark.asyncio
async def test_rpc_leftover_combo_does_not_promote_other_turn() -> None:
    from diana.telegram.keyboards import encode_reprimand_confirm

    g = _graph(feature_on=True)
    turn_a = await _queue_draft(g, vip_id=uuid4())
    turn_b = await _queue_draft(g, vip_id=uuid4())
    candidate_b = uuid4()
    g["sessions"].start(OWNER, turn_b.id, mode="reprimand", chat_id=42)
    g["sessions"].capture_reprimand(
        OWNER, candidate_id=candidate_b, corrected_text="from B"
    )
    reprimand = AsyncMock(wraps=g["admin"].handle_reprimand)
    g["admin"].handle_reprimand = reprimand  # type: ignore[method-assign]
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_reprimand_confirm(turn_a.id, "ex", "g"),
        actor_id=OWNER,
    )
    assert status == "reprimand_lesson_not_saved"
    reprimand.assert_not_awaited()
    live = g["sessions"].get_session(OWNER)
    assert live is not None
    assert live.turn_id == turn_b.id


@pytest.mark.asyncio
async def test_start_reprimand_cancels_previous_combo() -> None:
    from diana.telegram.keyboards import encode_reprimand_confirm

    g = _graph(feature_on=True)
    turn_a = await _queue_draft(g, vip_id=uuid4())
    turn_b = await _queue_draft(g, vip_id=uuid4())
    g["sessions"].start(OWNER, turn_a.id, mode="reprimand", chat_id=42)
    g["sessions"].capture_reprimand(
        OWNER, candidate_id=uuid4(), corrected_text="from A"
    )
    status = await _dispatch(g, "reprimand", turn_b.id)
    assert status == "awaiting_reprimand"
    sess = g["sessions"].get_session(OWNER)
    assert sess is not None
    assert sess.turn_id == turn_b.id
    assert sess.phase == "await_text"
    assert sess.candidate_id is None
    leftover = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_reprimand_confirm(turn_a.id, "ex", "g"),
        actor_id=OWNER,
    )
    assert leftover == "reprimand_lesson_not_saved"


@pytest.mark.asyncio
async def test_reprimand_failed_delivery_does_not_open_combo() -> None:
    from diana.application.memory import InMemoryVipStore
    from diana.application.ports import DeliveryResult

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    await _dispatch(g, "reprimand", turn.id)
    g["admin"].handle_correct_with_candidate = AsyncMock(  # type: ignore[method-assign]
        return_value=(
            DeliveryResult(success=False, cancelled=False, error="send failed"),
            uuid4(),
        )
    )
    token = await handle_admin_text(
        text="nunca llegó",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=g["sessions"],
    )
    assert token == "deliver_failed"
    assert g["sessions"].get(OWNER) is None


@pytest.mark.asyncio
async def test_gdc_cancel_atencion_refuses() -> None:
    from diana.telegram.keyboards import encode_gold_confirm

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=None, channel_type="atencion")
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_gold_confirm(turn.id, "x"),
        actor_id=OWNER,
    )
    assert status == "quality_feedback_not_vip"


@pytest.mark.asyncio
async def test_gold_scope_cancel_rebuilds_with_vip_flag_gate() -> None:
    from aiogram.types import CallbackQuery, Chat, Message, User

    from diana.telegram.handlers.callbacks import build_callback_router
    from diana.telegram.keyboards import encode_gold_confirm

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    router = build_callback_router(
        admin=g["admin"],
        owner_telegram_id=OWNER,
        correct_sessions=g["sessions"],
    )
    on_cb = router.callback_query.handlers[0].callback
    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="draft",
    )
    object.__setattr__(msg, "edit_reply_markup", AsyncMock(return_value=True))
    query = CallbackQuery(
        id="cq-gdc-x",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_gold_confirm(turn.id, "x"),
        message=msg,
    )
    object.__setattr__(query, "answer", AsyncMock(return_value=True))
    await on_cb(query)
    query.answer.assert_awaited_once_with()
    kb = msg.edit_reply_markup.await_args.kwargs["reply_markup"]
    cbs = [b.callback_data or "" for row in kb.inline_keyboard for b in row]
    assert any(cb.startswith("gd:") for cb in cbs)


@pytest.mark.asyncio
async def test_quality_tokens_do_not_reanswer_callback() -> None:
    from aiogram.types import CallbackQuery, Chat, Message, User

    from diana.telegram.handlers.callbacks import (
        _QUALITY_ALERTS,
        build_callback_router,
    )
    from diana.telegram.keyboards import encode_reprimand_confirm

    g = _graph(feature_on=True)
    turn = await _queue_draft(g, vip_id=uuid4())
    router = build_callback_router(
        admin=g["admin"],
        owner_telegram_id=OWNER,
        correct_sessions=g["sessions"],
    )
    on_cb = router.callback_query.handlers[0].callback
    msg = Message(
        message_id=9,
        date=0,
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        text="draft",
    )
    object.__setattr__(msg, "answer", AsyncMock(return_value=True))
    object.__setattr__(msg, "edit_reply_markup", AsyncMock(return_value=True))
    query = CallbackQuery(
        id="cq-rpc",
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        chat_instance="inst",
        data=encode_reprimand_confirm(turn.id, "ex", "g"),
        message=msg,
    )
    object.__setattr__(query, "answer", AsyncMock(return_value=True))
    await on_cb(query)
    query.answer.assert_awaited_once_with()
    msg.answer.assert_awaited()
    assert msg.answer.await_args.args[0] == _QUALITY_ALERTS["reprimand_lesson_not_saved"]


@pytest.mark.asyncio
async def test_reprimand_sandbox_lesson_not_saved_clear_token() -> None:
    """Sandbox: Reprender entrega el texto pero NO persiste la lección.

    El criterio (dueña, 2026-08-25): en sandbox la memoria del usuario es
    efímera; las decisiones de doctrina persisten. Por eso la lección no se
    guarda — y el token debe distinguir el aislamiento del sandbox para que el
    mensaje no suene a error.
    """
    from diana.application.memory import InMemoryVipStore
    from diana.application.sandbox import SandboxService
    from tests.unit.application.test_admin_quality_feedback import _MINIMAL_SIX

    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(42, "nuevo")
    staging, _ = _real_staging(sandbox=sandbox)
    g, turn, _, _ = await _pending_vip_draft(staging=staging, vip_id=uuid4())
    sessions = CorrectSessionStore()
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=sessions,
        callback_data=encode_callback("reprimand", turn.id),
        actor_id=OWNER,
    )
    token = await handle_admin_text(
        text="texto corregido en sandbox",
        actor_id=OWNER,
        owner_telegram_id=OWNER,
        vips=InMemoryVipStore(),
        admin=g["admin"],
        correct_sessions=sessions,
        sandbox=sandbox,
    )
    # Aislamiento sandbox: no hay candidato → token distinto, no genérico.
    assert token == "reprimand_lesson_not_saved_sandbox"
    assert sessions.get(OWNER) is None
    assert g["actuator"].send_count() >= 1
