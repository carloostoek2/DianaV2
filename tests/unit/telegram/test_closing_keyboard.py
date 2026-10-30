"""Cierre silencioso en la cola de la dueña (AGENTS §4.26).

Cubre el botón "🤐 Cerrar sin responder": aparece SOLO cuando el candado
determinista se activó, su callback va y vuelve, y al pulsarlo el turno cierra
sin entregar nada al VIP.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.application.draft_variants import (
    CLOSING_REASON,
    APPROVAL_REASON_LABELS,
    offers_closing_without_reply,
)
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
)
from diana.application.admin_service import AdminService
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import FakeTelegramActuator, FixedDelayPolicy, ImmediateClock
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn, TurnStatus
from diana.telegram.handlers.callbacks import (
    CorrectSessionStore,
    dispatch_owner_callback,
)
from diana.telegram.keyboards import draft_keyboard, encode_callback, parse_callback

OWNER = 999001
OTHER = 111


def _all_callback_data(kb) -> list[str]:
    return [b.callback_data or "" for row in kb.inline_keyboard for b in row]


def _all_labels(kb) -> list[str]:
    return [b.text or "" for row in kb.inline_keyboard for b in row]


class TestClosingKeyboard:
    def test_button_absent_by_default(self) -> None:
        kb = draft_keyboard(uuid4(), chat_id=42)
        assert "🤐 Cerrar sin responder" not in _all_labels(kb)

    def test_button_present_when_the_latch_fired(self) -> None:
        tid = uuid4()
        kb = draft_keyboard(tid, chat_id=42, show_close_without_reply=True)
        assert "🤐 Cerrar sin responder" in _all_labels(kb)
        assert f"cn:{tid}" in _all_callback_data(kb)

    def test_button_gets_its_own_row_below_the_primary_actions(self) -> None:
        """Es una alternativa a Aprobar, pero en su propia fila (no parte del trío)."""
        kb = draft_keyboard(uuid4(), chat_id=42, show_close_without_reply=True)
        assert [b.text for b in kb.inline_keyboard[0]] == [
            "✅ Aprobar",
            "✏️ Corregir",
            "⚠️ Escalar",
        ]
        assert [b.text for b in kb.inline_keyboard[1]] == ["🤐 Cerrar sin responder"]

    def test_callback_roundtrip(self) -> None:
        tid = uuid4()
        data = encode_callback("close_no_reply", tid)
        assert parse_callback(data) == ("close_no_reply", tid)

    def test_callback_fits_telegram_limit(self) -> None:
        data = encode_callback("close_no_reply", uuid4())
        assert len(data.encode("utf-8")) <= 64


class TestClosingReason:
    def test_matches_the_machine_token(self) -> None:
        assert offers_closing_without_reply(CLOSING_REASON) is True
        assert offers_closing_without_reply(f"  {CLOSING_REASON} ") is True

    def test_other_reasons_do_not_offer_it(self) -> None:
        for reason in ("ok_for_human_review", "autonomous_ok", "", None):
            assert offers_closing_without_reply(reason) is False

    def test_reason_has_a_legible_label(self) -> None:
        """La dueña nunca ve el token crudo en el borrador ni en la traza."""
        assert CLOSING_REASON in APPROVAL_REASON_LABELS
        assert "cerrar sin responder" in APPROVAL_REASON_LABELS[CLOSING_REASON]


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
        "notifier": notifier,
        "sessions": CorrectSessionStore(),
    }


async def _queue_closing_draft(g: dict, reason: str = CLOSING_REASON):
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    decision = Decision(
        action="approve",
        reason=reason,
        evaluation=_eval(),
        draft_text="que descanses",
    )
    await g["admin"].send_draft_for_approval(
        IncomingTurn(
            turn_id=turn.id,
            chat_id=42,
            text="bye",
            business_connection_id="bc-1",
            telegram_message_id=7,
        ),
        decision,
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    return turn


@pytest.mark.asyncio
async def test_callback_closes_without_delivering(graph: dict) -> None:
    g = graph
    turn = await _queue_closing_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("close_no_reply", turn.id),
        actor_id=OWNER,
    )
    assert status == "closed_no_reply"
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == TurnStatus.CLOSED_NO_REPLY.value
    approval = await g["approvals"].get_by_turn(turn.id)
    assert approval is not None and approval.status == "cancelled"


@pytest.mark.asyncio
async def test_non_owner_cannot_close(graph: dict) -> None:
    g = graph
    turn = await _queue_closing_draft(g)
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("close_no_reply", turn.id),
        actor_id=OTHER,
    )
    assert status == "forbidden"
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status != TurnStatus.CLOSED_NO_REPLY.value


@pytest.mark.asyncio
async def test_stale_close_button_reports_honestly(graph: dict) -> None:
    """Un botón viejo sobre un turno ya resuelto no inventa un cierre."""
    g = graph
    turn = await _queue_closing_draft(g, reason="ok_for_human_review")
    await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("approve", turn.id),
        actor_id=OWNER,
    )
    status = await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_callback("close_no_reply", turn.id),
        actor_id=OWNER,
    )
    assert status != "closed_no_reply"
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "delivered"
