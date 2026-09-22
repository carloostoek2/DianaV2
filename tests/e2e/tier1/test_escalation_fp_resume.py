"""E2E: false positive → the flow continues with the draft (AGENTS §4.21)."""

from __future__ import annotations

from uuid import UUID

import pytest

from diana.application.deterministic_escalate import (
    handle_deterministic_escalation,
)
from diana.application.ports import VipInboundMessage
from diana.cognitive.models import Decision, TurnStatus
from diana.telegram.handlers.callbacks import dispatch_owner_callback
from diana.telegram.keyboards import encode_escalation_callback
from tests.e2e.conftest import make_eval
from tests.e2e.tier1.conftest import OWNER_ID, build_e2e, dispatch

CHAT_ID = 100
BC = "bc-vip"


async def _tap_false_positive(g: dict, turn_id: UUID, *, actor_id: int = OWNER_ID) -> str:
    """Owner taps "➖ Falso positivo" on the escalation DM."""
    return await dispatch_owner_callback(
        admin=g["admin"],
        correct_sessions=g["sessions"],
        callback_data=encode_escalation_callback("fp", turn_id),
        actor_id=actor_id,
        owner_telegram_id=OWNER_ID,
    )


def _decision(**kw) -> Decision:
    data = {
        "action": "approve",
        "reason": "ok_for_human_review",
        "evaluation": make_eval(),
        "draft_text": "borrador",
    }
    data.update(kw)
    return Decision(**data)


async def _escalated_with_draft(g: dict, *, reason: str) -> UUID:
    """Escalate a VIP message and seed the trace the pipeline would have left."""
    g["director"]._decisions.insert(  # noqa: SLF001
        0, _decision(action="escalate", reason=reason, draft_text="")
    )
    msg = VipInboundMessage(
        chat_id=CHAT_ID,
        text="¿me puedes ayudar con esto?",
        telegram_message_id=1,
        business_connection_id=BC,
    )
    turn_id = await g["orch"].handle_vip_message(msg)
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED
    await g["traces"].store(turn_id, "generated_text", "borrador ya generado")
    await g["traces"].store(turn_id, "decision", {"reason": reason})
    return turn_id


@pytest.mark.asyncio
async def test_fp_reuses_the_persisted_draft_and_delivers() -> None:
    """Semantic escalation: the draft the pipeline already wrote reaches the VIP."""
    g = build_e2e([], feature_escalation_fp_draft_enabled=True)
    turn_id = await _escalated_with_draft(g, reason="risk_high")
    calls_before = len(g["director"].calls)  # noqa: SLF001

    assert await _tap_false_positive(g, turn_id) == "escalation_fp_draft_sent"

    # Reused, not regenerated.
    assert len(g["director"].calls) == calls_before  # noqa: SLF001
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].draft_text == "borrador ya generado"
    assert (await g["turns"].get(turn_id)).status == TurnStatus.PENDING_APPROVAL

    assert await dispatch("approve", turn_id, g) == "approved"

    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "borrador ya generado"
    assert (await g["turns"].get(turn_id)).status == TurnStatus.DELIVERED


@pytest.mark.asyncio
async def test_fp_generates_a_draft_for_a_deterministic_escalation() -> None:
    """Deterministic short-circuit (no pipeline at all): the draft is generated."""
    g = build_e2e(
        [_decision(draft_text="borrador generado para el VIP")],
        feature_escalation_fp_draft_enabled=True,
    )
    turn_id = await handle_deterministic_escalation(
        coordinator=g["coordinator"],
        escalations=g["escalations"],
        notifier=g["notifier"],
        chat_id=CHAT_ID,
        text="cuánto cuesta el plan?",
        vip_id=None,
        business_connection_id=BC,
        message_id=9,
        keywords_hit=["cuesta"],
        history=g["history"],
    )

    assert await _tap_false_positive(g, turn_id) == "escalation_fp_draft_sent"

    assert g["notifier"].drafts[-1].draft_text == "borrador generado para el VIP"
    # The H4 repetition guard is skipped for the owner's resume.
    assert g["director"].kwargs == [{"skip_repetition_guard": True}]  # noqa: SLF001
    assert (await g["turns"].get(turn_id)).status == TurnStatus.PENDING_APPROVAL

    assert await dispatch("approve", turn_id, g) == "approved"
    assert g["actuator"].send_count() == 1


@pytest.mark.asyncio
async def test_fp_on_a_safety_escalation_never_enqueues_the_draft() -> None:
    g = build_e2e([], feature_escalation_fp_draft_enabled=True)
    turn_id = await _escalated_with_draft(g, reason="safety_below_threshold")

    assert await _tap_false_positive(g, turn_id) == "escalation_fp_blocked_safety"

    assert g["notifier"].drafts == []
    assert await g["approvals"].get_by_turn(turn_id) is None
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_fp_keeps_one_live_turn_per_chat_when_the_vip_wrote_again() -> None:
    """A newer message owns the chat: the escalation stays closed, no draft."""
    g = build_e2e([_decision(draft_text="respuesta al mensaje nuevo")],
                  feature_escalation_fp_draft_enabled=True)
    turn_id = await _escalated_with_draft(g, reason="risk_high")
    newer = await g["orch"].handle_vip_message(
        VipInboundMessage(
            chat_id=CHAT_ID,
            text="mensaje nuevo",
            telegram_message_id=2,
            business_connection_id=BC,
        )
    )
    assert newer != turn_id

    drafts_before = len(g["notifier"].drafts)
    # The owner is told *why* no draft came: a newer message owns the chat.
    assert (
        await _tap_false_positive(g, turn_id) == "escalation_fp_skipped_new_turn"
    )

    live = await g["turns"].list_non_terminal(CHAT_ID)
    assert len(live) == 1 and live[0].id == newer
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED
    # The only draft DM is the newer turn's own; the escalation sent none.
    assert len(g["notifier"].drafts) == drafts_before
    assert all(d.turn_id == newer for d in g["notifier"].drafts)


@pytest.mark.asyncio
async def test_fp_with_the_flag_off_behaves_as_before() -> None:
    g = build_e2e([])
    turn_id = await _escalated_with_draft(g, reason="risk_high")

    assert await _tap_false_positive(g, turn_id) == "escalation_fp_marked"

    assert g["notifier"].drafts == []
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_fp_requires_the_owner() -> None:
    g = build_e2e([], feature_escalation_fp_draft_enabled=True)
    turn_id = await _escalated_with_draft(g, reason="risk_high")

    assert (
        await _tap_false_positive(g, turn_id, actor_id=OWNER_ID + 1) == "forbidden"
    )
    assert g["notifier"].drafts == []


@pytest.mark.asyncio
async def test_fp_after_a_newer_message_was_answered_stays_stale() -> None:
    """The stale guard also covers turns that are no longer live (delivered)."""
    g = build_e2e(
        [_decision(draft_text="respuesta al mensaje nuevo")],
        feature_escalation_fp_draft_enabled=True,
    )
    turn_id = await _escalated_with_draft(g, reason="risk_high")
    newer = await g["orch"].handle_vip_message(
        VipInboundMessage(
            chat_id=CHAT_ID,
            text="mensaje nuevo",
            telegram_message_id=2,
            business_connection_id=BC,
        )
    )
    assert await dispatch("approve", newer, g) == "approved"
    drafts_before = len(g["notifier"].drafts)

    # The old escalation must not answer the chat after the newer message did.
    assert await _tap_false_positive(g, turn_id) == "escalation_fp_stale"

    assert len(g["notifier"].drafts) == drafts_before
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED
    assert g["actuator"].send_count() == 1


@pytest.mark.asyncio
async def test_fp_reply_then_false_positive_does_not_duplicate() -> None:
    """Her manual reply for the same turn is the answer: no second message."""
    g = build_e2e([], feature_escalation_fp_draft_enabled=True)
    turn_id = await _escalated_with_draft(g, reason="risk_high")

    delivered = await g["admin"].handle_escalation_reply(
        turn_id, "respuesta manual de la dueña", actor_id=OWNER_ID
    )
    assert delivered is not None and delivered.success is True

    assert (
        await _tap_false_positive(g, turn_id) == "escalation_fp_skipped_owner_wrote"
    )

    assert g["notifier"].drafts == []
    assert g["actuator"].send_count() == 1
