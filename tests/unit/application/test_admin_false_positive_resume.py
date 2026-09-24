"""False-positive resume: mark + continue the supervised flow (AGENTS §4.21)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from diana.application.admin_service import OwnerAuthError
from diana.application.escalation_fp_resume import (
    RESUME_BLOCKED_SAFETY,
    RESUME_MARKED_ONLY,
    RESUME_OPENED_GRAY_ZONE,
    RESUME_RESUMED,
    fp_resume_key,
)
from diana.application.memory import InMemoryMessageHistoryWriter
from diana.application.owner_marks import InMemoryOwnerMarkStore
from diana.application.ports import ApprovalRecord
from diana.cognitive.models import Decision, TurnStatus
from tests.unit.application.test_admin_service import (
    _admin_graph,
    _decision,
    _eval,
)

OWNER_ID = 999001
OTHER_USER = 123
CHAT_ID = 42
BC = "bc-1"


class FakeDirector:
    """Records handle_turn calls and returns an enqueued decision."""

    def __init__(self, decision: Decision | None = None) -> None:
        self.decision = decision or _decision(draft="borrador generado")
        self.calls: list[tuple[object, dict]] = []

    async def handle_turn(self, incoming, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append((incoming, kwargs))
        return self.decision


class FakeGrayZone:
    """Minimal gray-zone port for FP → consult_doctrine tests."""

    def __init__(self) -> None:
        self.queries: list[dict] = []
        self.discarded: list[UUID] = []
        self.open_by_chat: dict[int, object] = {}
        self._next_id = uuid4()
        self.fail_create = False

    async def create_query(self, vip_id, turn_id, question, draft, **kwargs):  # noqa: ANN001, ANN003
        if self.fail_create:
            raise RuntimeError("create_query failed")
        row = {
            "vip_id": vip_id,
            "turn_id": turn_id,
            "question": question,
            "draft": draft,
            **kwargs,
        }
        self.queries.append(row)
        return SimpleNamespace(id=self._next_id, vip_id=vip_id, turn_id=turn_id)

    async def get_open_query_by_chat_id(self, chat_id: int) -> object | None:
        return self.open_by_chat.get(chat_id)

    async def discard_and_close(self, query_id: UUID) -> object:
        self.discarded.append(query_id)
        return SimpleNamespace(id=query_id)


def _graph(**kwargs) -> dict:
    kwargs.setdefault("feature_escalation_fp_draft_enabled", True)
    g = _admin_graph(**kwargs)
    g["admin"]._fp_marks = InMemoryOwnerMarkStore()  # noqa: SLF001
    return g


async def _escalated_turn(
    g: dict,
    *,
    bc: str | None = BC,
    vip_text: str | None = None,
    trigger_message_id: int = 7,
) -> UUID:
    """Mint an escalated turn with its escalation record (and vip history)."""
    turn = await g["coordinator"].begin_turn(
        chat_id=CHAT_ID, trigger_message_id=trigger_message_id
    )
    await g["coordinator"].transition(turn.id, TurnStatus.ESCALATED)
    if bc is not None:
        await g["escalations"].create(
            turn.id, tipo="semantica", motivo="risk_high", business_connection_id=bc
        )
    if vip_text is not None:
        await g["history"].append(
            CHAT_ID,
            role="vip",
            text=vip_text,
            telegram_message_id=trigger_message_id,
        )
    return turn.id


def _seed_trace(g: dict, turn_id: UUID, *, draft: str | None, reason: str) -> None:
    g["traces"].data[turn_id] = {}
    if draft is not None:
        g["traces"].data[turn_id]["generated_text"] = draft
    g["traces"].data[turn_id]["decision"] = {"reason": reason}
    g["traces"].data[turn_id]["evaluation"] = _eval().model_dump(mode="json")


async def _no_approval(g: dict, turn_id: UUID) -> bool:
    return await g["approvals"].get_by_turn(turn_id) is None


# --- reuse path (the common semantic escalation) ----------------------------


@pytest.mark.asyncio
async def test_resume_reuses_trace_draft_and_enqueues_approval() -> None:
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador ya generado", reason="risk_high")
    director = FakeDirector()
    g["admin"]._director = director  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_RESUMED
    # The persisted draft is reused: no LLM work at all.
    assert director.calls == []
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.status == "waiting"
    assert approval.draft_text == "borrador ya generado"
    assert approval.business_connection_id == BC
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].draft_text == "borrador ya generado"
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == TurnStatus.PENDING_APPROVAL
    # The triage mark is recorded for metrics.
    marks = g["admin"]._fp_marks  # noqa: SLF001
    assert await marks.count_in_range(date(2000, 1, 1), date(2100, 1, 1)) == 1


@pytest.mark.asyncio
async def test_resume_reuses_the_decision_draft_when_generated_text_is_missing() -> None:
    """Trace rows written by a decision-only path still carry a reusable draft."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    g["traces"].data[turn_id] = {
        "decision": {"reason": "risk_high", "draft_text": "borrador del decisor"}
    }
    director = FakeDirector()
    g["admin"]._director = director  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    assert director.calls == []
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.draft_text == "borrador del decisor"


# --- generation path (no draft: H4 / deterministic escalations) -------------


@pytest.mark.asyncio
async def test_resume_generates_draft_when_trace_has_none() -> None:
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿cuánto cuesta?")
    director = FakeDirector(_decision(draft="respuesta generada"))
    g["admin"]._director = director  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    assert len(director.calls) == 1
    incoming, kwargs = director.calls[0]
    assert incoming.text == "¿cuánto cuesta?"
    assert incoming.business_connection_id == BC
    # The H4 repetition guard is skipped for the owner's resume.
    assert kwargs == {"skip_repetition_guard": True}
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.draft_text == "respuesta generada"
    # Nombre del motivo localizado por la UI (no el token crudo).
    assert approval.cognitive_summary == "escalation_false_positive_resume"


@pytest.mark.asyncio
async def test_resume_without_vip_text_stays_marked_only() -> None:
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g)  # no history row for the VIP message
    director = FakeDirector()
    g["admin"]._director = director  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "no_vip_text"
    assert fp_resume_key(outcome) == "skipped_no_vip_text"
    # Fail-closed before the LLM: the text is pipeline input, never fabricated.
    assert director.calls == []
    assert await _no_approval(g, turn_id)
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_without_director_stays_marked_only() -> None:
    """No Director wired (flag ON, generation needed): honest no-op, no DM."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿cuánto cuesta?")
    g["admin"]._director = None  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "no_director"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_generated_safety_escalation_blocks() -> None:
    """Second safety origin: the regenerated decision escalates by safety."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿cuánto cuesta?")
    g["admin"]._director = FakeDirector(  # noqa: SLF001
        _decision(
            action="escalate",
            draft="borrador inseguro",
            reason="safety_below_threshold",
        )
    )

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_BLOCKED_SAFETY
    # The owner gets the safety message, not a bare "marcado" (the raw decision
    # reason stays in the log).
    assert outcome.detail == "no_draft_generated"
    assert fp_resume_key(outcome) == "blocked_safety"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_superseded_while_generating_stays_marked_only() -> None:
    """The VIP wrote again: the pipeline supersede aborts the resume cleanly."""
    from diana.cognitive.exceptions import TurnSupersededError

    class _SupersededDirector(FakeDirector):
        async def handle_turn(self, incoming, **kwargs):  # noqa: ANN001, ANN003
            raise TurnSupersededError("newer message owns the chat")

    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿cuánto cuesta?")
    g["admin"]._director = _SupersededDirector()  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "superseded"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_generates_with_the_atencion_channel() -> None:
    """The resumed pipeline keeps the persona channel of the escalated turn."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn = await g["coordinator"].begin_turn(
        chat_id=CHAT_ID, trigger_message_id=7, channel_type="atencion"
    )
    await g["coordinator"].transition(turn.id, TurnStatus.ESCALATED)
    await g["escalations"].create(
        turn.id, tipo="semantica", motivo="risk_high", business_connection_id=BC
    )
    await g["history"].append(
        CHAT_ID, role="vip", text="¿cuánto cuesta?", telegram_message_id=7
    )
    director = FakeDirector(_decision(draft="respuesta de atención"))
    g["admin"]._director = director  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn.id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    incoming, _ = director.calls[0]
    assert incoming.channel_type == "atencion"
    approval = await g["approvals"].get_by_turn(turn.id)
    assert approval is not None and approval.draft_text == "respuesta de atención"


@pytest.mark.asyncio
async def test_resume_generation_consult_doctrine_opens_gray_zone() -> None:
    """consult_doctrine after FP opens gray zone + doctrine DM (no approval)."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿tienen garantía?")
    gz = FakeGrayZone()
    g["admin"]._gray_zone = gz  # noqa: SLF001
    g["admin"]._director = FakeDirector(  # noqa: SLF001
        _decision(
            action="consult_doctrine",
            draft="borrador que la regla no respalda",
            reason="doctrine_not_found",
        )
    )

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_OPENED_GRAY_ZONE
    assert fp_resume_key(outcome) == "opened_gray_zone"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []
    assert len(g["notifier"].doctrines) == 1
    assert g["notifier"].doctrines[0].draft_text == "borrador que la regla no respalda"
    assert len(gz.queries) == 1
    assert gz.queries[0]["question"] == "¿tienen garantía?"
    assert gz.discarded == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == TurnStatus.GRAY_ZONE


@pytest.mark.asyncio
async def test_resume_consult_doctrine_without_gray_zone_fails_closed() -> None:
    """Gray zone not wired → honest mark-only, no crash."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿tienen garantía?")
    g["admin"]._gray_zone = None  # noqa: SLF001
    g["admin"]._director = FakeDirector(  # noqa: SLF001
        _decision(
            action="consult_doctrine",
            draft="borrador doctrinal",
            reason="doctrine_not_found",
        )
    )

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "gray_zone_unavailable"
    assert fp_resume_key(outcome) == "skipped_unavailable"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].doctrines == []
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_consult_doctrine_notify_failure_discards_query() -> None:
    """Notify failure must not leave an orphan freeze / half-open gray_zone."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿tienen garantía?")
    gz = FakeGrayZone()
    g["admin"]._gray_zone = gz  # noqa: SLF001
    g["admin"]._director = FakeDirector(  # noqa: SLF001
        _decision(
            action="consult_doctrine",
            draft="borrador doctrinal",
            reason="doctrine_not_found",
        )
    )

    async def _boom(*_a, **_k):  # noqa: ANN001, ANN002
        raise RuntimeError("telegram down")

    g["admin"].send_doctrine_query = _boom  # type: ignore[method-assign]

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "doctrine_notify_failed"
    assert len(gz.queries) == 1
    assert gz.discarded == [gz._next_id]  # noqa: SLF001
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED
    assert g["notifier"].doctrines == []


@pytest.mark.asyncio
async def test_resume_generation_with_empty_draft_sends_no_draft() -> None:
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿cuánto cuesta?")
    g["admin"]._director = FakeDirector(  # noqa: SLF001
        _decision(action="approve", draft="   ", reason="ok")
    )

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "no_draft_generated"
    assert fp_resume_key(outcome) == "skipped_no_draft_generated"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []


@pytest.mark.asyncio
async def test_empty_draft_on_a_safety_escalation_keeps_the_safety_status() -> None:
    """The safety label comes from the reason: an empty draft must not eat it."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿cuánto cuesta?")
    g["admin"]._director = FakeDirector(  # noqa: SLF001
        _decision(action="escalate", draft="", reason="safety_below_threshold")
    )

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_BLOCKED_SAFETY
    assert outcome.detail == "no_draft_generated"
    assert fp_resume_key(outcome) == "blocked_safety"


@pytest.mark.asyncio
async def test_resume_generation_that_re_escalates_by_risk_is_not_a_failure() -> None:
    """The Director re-attaches the draft on escalate: the owner decides from her queue."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="quiero cerrar el trato")
    g["admin"]._director = FakeDirector(  # noqa: SLF001
        _decision(action="escalate", draft="borrador con riesgo", reason="risk_high")
    )

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.status == "waiting"
    assert approval.draft_text == "borrador con riesgo"


# --- safety fail-closed -----------------------------------------------------


@pytest.mark.asyncio
async def test_resume_blocked_by_safety_marks_only() -> None:
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(
        g, turn_id, draft="borrador inseguro", reason="safety_below_threshold"
    )
    g["admin"]._director = FakeDirector()  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_BLOCKED_SAFETY
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == TurnStatus.ESCALATED


# --- guards -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_refuses_when_another_turn_is_live() -> None:
    """One live turn per chat is non-negotiable: the newer message owns the chat."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")
    newer = await g["coordinator"].begin_turn(chat_id=CHAT_ID)
    assert newer.id != turn_id

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "chat_busy"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []
    # The newer live turn is untouched.
    assert (await g["turns"].get(newer.id)).status != TurnStatus.ESCALATED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        TurnStatus.PENDING_APPROVAL,
        TurnStatus.DELIVERED,
        TurnStatus.SUPERSEDED,
        TurnStatus.FAILED,
    ],
)
async def test_resume_refuses_when_turn_is_not_escalated(status: str) -> None:
    g = _graph()
    turn = await g["coordinator"].begin_turn(chat_id=CHAT_ID)
    await g["coordinator"].transition(turn.id, status)
    if status == TurnStatus.ESCALATED:
        raise AssertionError("escalated is covered by the resume tests")
    await g["escalations"].create(
        turn.id, tipo="semantica", motivo="risk_high", business_connection_id=BC
    )
    _seed_trace(g, turn.id, draft="borrador", reason="risk_high")

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn.id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_MARKED_ONLY
    # delivered is the durable close after a manual reply/approve → owner_wrote
    expected = (
        "owner_intervened"
        if status == TurnStatus.DELIVERED
        else "not_escalated"
    )
    assert outcome.detail == expected
    assert await _no_approval(g, turn.id)
    assert (await g["turns"].get(turn.id)).status == status


@pytest.mark.asyncio
async def test_resume_without_business_connection_fails_closed() -> None:
    g = _graph()
    turn_id = await _escalated_turn(g, bc=None)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "no_business_connection"
    assert await _no_approval(g, turn_id)


@pytest.mark.asyncio
async def test_resume_uses_approval_bc_when_no_escalation_event() -> None:
    """Owner-escalated drafts write no escalation event but carry the BC."""
    g = _graph()
    turn = await g["coordinator"].begin_turn(chat_id=CHAT_ID)
    await g["coordinator"].transition(turn.id, TurnStatus.ESCALATED)
    _seed_trace(g, turn.id, draft="borrador", reason="risk_high")
    await g["approvals"].create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn.id,
            chat_id=CHAT_ID,
            business_connection_id="bc-approval",
            draft_text="borrador",
            status="waiting",
        )
    )

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn.id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    # The pre-existing waiting approval is reused: no second DM.
    assert g["notifier"].drafts == []
    assert (await g["turns"].get(turn.id)).status == TurnStatus.PENDING_APPROVAL


@pytest.mark.asyncio
async def test_resume_is_idempotent_on_second_tap() -> None:
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    first = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )
    second = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert first.status == RESUME_RESUMED
    assert second.status == RESUME_MARKED_ONLY
    assert second.detail == "not_escalated"
    assert len(g["notifier"].drafts) == 1


@pytest.mark.asyncio
async def test_resume_flag_off_marks_only_and_does_not_touch_the_flow() -> None:
    g = _graph(feature_escalation_fp_draft_enabled=False)
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "flag_off"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_requires_owner() -> None:
    g = _graph()
    turn_id = await _escalated_turn(g)

    with pytest.raises(OwnerAuthError):
        await g["admin"].mark_false_positive_and_resume(turn_id, actor_id=OTHER_USER)


@pytest.mark.asyncio
async def test_resume_without_mark_store_reports_failure() -> None:
    g = _graph()
    g["admin"]._fp_marks = None  # noqa: SLF001
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is False
    assert g["notifier"].drafts == []


@pytest.mark.asyncio
async def test_resume_owner_intervened_skips_the_draft() -> None:
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")
    g["coordinator"].mark_owner_intervened(CHAT_ID)

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "owner_intervened"
    assert await _no_approval(g, turn_id)


@pytest.mark.asyncio
async def test_resume_failure_after_approval_creation_leaves_no_orphan() -> None:
    """A fault while enqueuing cancels the approval and keeps the turn escalated."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    async def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("reopen exploded")

    g["turns"].reopen_from_escalated = _boom  # type: ignore[method-assign]

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "error"
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.status == "cancelled"
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_recreates_over_a_cancelled_approval_leftover() -> None:
    """Owner-escalated draft (approval cancelled) can be resumed from FP."""
    g = _graph()
    turn = await g["coordinator"].begin_turn(chat_id=CHAT_ID)
    await g["coordinator"].transition(turn.id, TurnStatus.ESCALATED)
    await g["escalations"].create(
        turn.id, tipo="semantica", motivo="risk_high", business_connection_id=BC
    )
    _seed_trace(g, turn.id, draft="borrador previo", reason="risk_high")
    await g["approvals"].create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn.id,
            chat_id=CHAT_ID,
            business_connection_id=BC,
            draft_text="borrador cancelado",
        )
    )
    await g["approvals"].mark_status(turn.id, "cancelled")

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn.id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    approval = await g["approvals"].get_by_turn(turn.id)
    assert approval is not None and approval.status == "waiting"
    assert approval.draft_text == "borrador previo"
    assert len(g["notifier"].drafts) == 1


# --- deferred / lost-race guards ---------------------------------------------


@pytest.mark.asyncio
async def test_resume_missing_turn_stays_marked_only() -> None:
    """A stale button from an old DM: the mark lands, nothing is resumed."""
    g = _graph()
    director = FakeDirector()
    g["admin"]._director = director  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        uuid4(), actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "missing_turn"
    assert director.calls == []
    assert g["notifier"].drafts == []


@pytest.mark.asyncio
async def test_resume_reopen_lost_cancels_the_approval() -> None:
    """CAS lost (turn stopped being escalated): no orphan waiting approval."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    async def _lost(turn_id, *, status="pending_approval"):  # noqa: ANN001
        return None

    g["turns"].reopen_from_escalated = _lost  # type: ignore[method-assign]

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "reopen_lost"
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.status == "cancelled"
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_refuses_when_an_approval_already_exists() -> None:
    """A claimed/approved approval for the turn blocks a second DM."""
    g = _graph()
    turn = await g["coordinator"].begin_turn(chat_id=CHAT_ID)
    await g["coordinator"].transition(turn.id, TurnStatus.ESCALATED)
    await g["escalations"].create(
        turn.id, tipo="semantica", motivo="risk_high", business_connection_id=BC
    )
    _seed_trace(g, turn.id, draft="borrador", reason="risk_high")
    await g["approvals"].create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn.id,
            chat_id=CHAT_ID,
            business_connection_id=BC,
            draft_text="borrador",
        )
    )
    await g["approvals"].mark_status(turn.id, "approved")

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn.id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "approval_exists"
    assert g["notifier"].drafts == []
    assert (await g["turns"].get(turn.id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_without_trace_reader_still_generates() -> None:
    """A trace store that is not a TraceReader degrades to generation."""
    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿cuánto cuesta?")
    director = FakeDirector(_decision(draft="respuesta generada"))
    g["admin"]._director = director  # noqa: SLF001
    g["admin"]._traces = object()  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    assert len(director.calls) == 1
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.draft_text == "respuesta generada"


# --- sandbox: mark isolated, resume still runs -------------------------------


@pytest.mark.asyncio
async def test_resume_in_sandbox_does_not_persist_the_mark_but_resumes() -> None:
    """Sandbox isolation keeps test feedback out of the metric, not out of the flow."""
    from diana.application.sandbox import SandboxService
    from tests.unit.application.test_admin_service import _MINIMAL_SIX

    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")
    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(CHAT_ID, "nuevo")
    g["admin"]._sandbox = sandbox  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_RESUMED
    marks = g["admin"]._fp_marks  # noqa: SLF001
    assert await marks.count_in_range(date(2000, 1, 1), date(2100, 1, 1)) == 0
    assert (await g["turns"].get(turn_id)).status == TurnStatus.PENDING_APPROVAL


# --- trace context and lost races ------------------------------------------


def _seed_trace_with_context(
    g: dict, turn_id: UUID, *, needs_policy: bool, policy: list | None
) -> None:
    """Trace as get_full_trace returns it: evaluation + comprehension + retrieved."""
    g["traces"].data[turn_id] = {
        "generated_text": "borrador con contexto",
        "decision": {"reason": "risk_high"},
        "evaluation": _eval().model_dump(mode="json"),
        "comprehension": {"needs_policy": needs_policy},
        "retrieved": {"knowledge.policy": policy or []},
    }


@pytest.mark.asyncio
async def test_resume_carries_trace_context_into_the_doctrine_display() -> None:
    """A turn that needed a rule keeps doctrine measured in the resumed DM."""
    from diana.application.draft_variants import DOCTRINE_RELEVANT_KEY

    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace_with_context(g, turn_id, needs_policy=True, policy=[])

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.evaluation is not None
    assert approval.evaluation[DOCTRINE_RELEVANT_KEY] is True


@pytest.mark.asyncio
async def test_resume_trace_context_without_a_rule_marks_doctrine_na() -> None:
    from diana.application.draft_variants import DOCTRINE_RELEVANT_KEY

    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace_with_context(g, turn_id, needs_policy=False, policy=[])

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.evaluation is not None
    assert approval.evaluation[DOCTRINE_RELEVANT_KEY] is False


@pytest.mark.asyncio
async def test_resume_superseded_during_generation_stays_marked_only() -> None:
    """A newer VIP message during the LLM run cancels the resume, not the mark."""
    from diana.cognitive.exceptions import TurnSupersededError

    class SupersedingDirector:
        async def handle_turn(self, incoming, **kwargs):  # noqa: ANN001, ANN003
            raise TurnSupersededError()

    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿sigues ahí?")
    g["admin"]._director = SupersedingDirector()  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.marked is True
    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "superseded"
    assert await _no_approval(g, turn_id)
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_lost_reopen_race_cancels_the_approval() -> None:
    """If the turn stops being escalated before the CAS, no orphan approval stays."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    original = g["turns"].reopen_from_escalated

    async def _lost(turn_id_arg, *, status="pending_approval"):  # noqa: ANN001
        return None

    g["turns"].reopen_from_escalated = _lost  # type: ignore[method-assign]
    try:
        outcome = await g["admin"].mark_false_positive_and_resume(
            turn_id, actor_id=OWNER_ID
        )
    finally:
        g["turns"].reopen_from_escalated = original  # type: ignore[method-assign]

    assert outcome.marked is True
    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "reopen_lost"
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.status == "cancelled"
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


# --- re-entrancy (two taps, one pipeline) ------------------------------------


@pytest.mark.asyncio
async def test_resume_refuses_a_second_tap_while_the_first_is_running() -> None:
    """aiogram runs one task per update: two taps must not run two pipelines."""
    import asyncio

    g = _graph(history=InMemoryMessageHistoryWriter())
    turn_id = await _escalated_turn(g, vip_text="¿cuánto cuesta?")
    entered = asyncio.Event()
    release = asyncio.Event()

    class _SlowDirector(FakeDirector):
        async def handle_turn(self, incoming, **kwargs):  # noqa: ANN001, ANN003
            entered.set()
            await release.wait()
            return await super().handle_turn(incoming, **kwargs)

    director = _SlowDirector(_decision(draft="borrador generado"))
    g["admin"]._director = director  # noqa: SLF001

    first = asyncio.create_task(
        g["admin"].mark_false_positive_and_resume(turn_id, actor_id=OWNER_ID)
    )
    await entered.wait()
    second = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )
    release.set()
    first_outcome = await first

    assert first_outcome.status == RESUME_RESUMED
    assert second.status == RESUME_MARKED_ONLY
    assert second.detail == "already_running"
    assert fp_resume_key(second) == "skipped_in_progress"
    # The loser never reaches the model nor creates a second approval DM.
    assert len(director.calls) == 1
    assert len(g["notifier"].drafts) == 1
    assert (await g["turns"].get(turn_id)).status == TurnStatus.PENDING_APPROVAL


@pytest.mark.asyncio
async def test_resume_inflight_guard_is_released_on_failure() -> None:
    """A fault while resuming must not lock the turn out of future taps."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    original = g["turns"].reopen_from_escalated

    async def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("reopen exploded")

    g["turns"].reopen_from_escalated = _boom  # type: ignore[method-assign]
    failed = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )
    g["turns"].reopen_from_escalated = original  # type: ignore[method-assign]
    retried = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert failed.detail == "error"
    assert retried.status == RESUME_RESUMED


# --- staleness beyond the live-turn guard ------------------------------------


@pytest.mark.asyncio
async def test_resume_refuses_when_a_newer_turn_was_already_delivered() -> None:
    """A delivered turn is invisible to list_non_terminal: check the store."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador viejo", reason="risk_high")
    newer = await g["coordinator"].begin_turn(chat_id=CHAT_ID, trigger_message_id=8)
    await g["coordinator"].transition(newer.id, TurnStatus.DELIVERED)

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "stale"
    assert fp_resume_key(outcome) == "stale"
    assert await _no_approval(g, turn_id)
    assert g["notifier"].drafts == []
    assert (await g["turns"].get(turn_id)).status == TurnStatus.ESCALATED


@pytest.mark.asyncio
async def test_resume_proceeds_when_the_escalated_turn_is_the_newest() -> None:
    """Port parity: the newest turn of the chat may resume even if it is older."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    assert await g["turns"].latest_turn_id(CHAT_ID) == turn_id

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED


# --- manual reply wins over the draft (both orders) --------------------------


@pytest.mark.asyncio
async def test_owner_manual_reply_leaves_turn_delivered() -> None:
    """Successful manual reply is a durable terminal: status becomes delivered."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    delivered = await g["admin"].handle_escalation_reply(
        turn_id, "te escribo yo", actor_id=OWNER_ID
    )

    assert delivered is not None and delivered.success is True
    assert g["coordinator"].is_owner_intervened(CHAT_ID) is True
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == TurnStatus.DELIVERED.value
    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )
    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "owner_intervened"
    assert fp_resume_key(outcome) == "skipped_owner_wrote"
    assert g["notifier"].drafts == []


@pytest.mark.asyncio
async def test_fp_resume_after_manual_reply_fails_closed_without_in_memory_flag() -> None:
    """Restart parity: after reply, clearing the process-local flag still blocks."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador", reason="risk_high")

    delivered = await g["admin"].handle_escalation_reply(
        turn_id, "te escribo yo", actor_id=OWNER_ID
    )
    assert delivered is not None and delivered.success is True
    g["coordinator"].clear_owner_intervention(CHAT_ID)
    assert g["coordinator"].is_owner_intervened(CHAT_ID) is False

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_MARKED_ONLY
    assert outcome.detail == "owner_intervened"
    assert fp_resume_key(outcome) == "skipped_owner_wrote"
    assert (await g["turns"].get(turn_id)).status == TurnStatus.DELIVERED.value
    assert g["notifier"].drafts == []


@pytest.mark.asyncio
async def test_owner_manual_reply_cancels_the_waiting_draft() -> None:
    """The reply wins: a draft already queued must not go out over it."""
    g = _graph()
    turn_id = await _escalated_turn(g)
    _seed_trace(g, turn_id, draft="borrador reusado", reason="risk_high")
    resumed = await g["admin"].mark_false_positive_and_resume(
        turn_id, actor_id=OWNER_ID
    )
    assert resumed.status == RESUME_RESUMED

    delivered = await g["admin"].handle_escalation_reply(
        turn_id, "respuesta manual", actor_id=OWNER_ID
    )

    assert delivered is not None and delivered.success is True
    approval = await g["approvals"].get_by_turn(turn_id)
    assert approval is not None and approval.status == "cancelled"
    stored = await g["turns"].get(turn_id)
    assert stored is not None and stored.status == TurnStatus.DELIVERED.value


# --- safety fallback without the trace (TTL purge) ---------------------------


@pytest.mark.asyncio
async def test_safety_escalation_blocks_from_the_persisted_motivo() -> None:
    """No trace at all: the persisted motivo keeps the safety block (and the LLM)."""
    g = _graph()
    turn = await g["coordinator"].begin_turn(chat_id=CHAT_ID, trigger_message_id=7)
    await g["coordinator"].transition(turn.id, TurnStatus.ESCALATED)
    await g["escalations"].create(
        turn.id,
        tipo="semantica",
        motivo="safety_below_threshold",
        business_connection_id=BC,
    )
    director = FakeDirector()
    g["admin"]._director = director  # noqa: SLF001

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn.id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_BLOCKED_SAFETY
    assert fp_resume_key(outcome) == "blocked_safety"
    assert director.calls == []
    assert await _no_approval(g, turn.id)
    assert (await g["turns"].get(turn.id)).status == TurnStatus.ESCALATED


# --- image of the resumed draft ----------------------------------------------


@pytest.mark.asyncio
async def test_resume_carries_the_photo_of_the_owner_draft() -> None:
    """The turn does not persist the image; its approval row still has it."""
    g = _graph()
    turn = await g["coordinator"].begin_turn(chat_id=CHAT_ID, trigger_message_id=7)
    await g["coordinator"].transition(turn.id, TurnStatus.ESCALATED)
    _seed_trace(g, turn.id, draft="borrador", reason="risk_high")
    await g["approvals"].create_waiting(
        ApprovalRecord(
            id=uuid4(),
            turn_id=turn.id,
            chat_id=CHAT_ID,
            business_connection_id=BC,
            draft_text="borrador cancelado",
            photo_file_id="photo-1",
        )
    )
    await g["approvals"].mark_status(turn.id, "cancelled")

    outcome = await g["admin"].mark_false_positive_and_resume(
        turn.id, actor_id=OWNER_ID
    )

    assert outcome.status == RESUME_RESUMED
    approval = await g["approvals"].get_by_turn(turn.id)
    assert approval is not None and approval.photo_file_id == "photo-1"
    assert g["notifier"].drafts[-1].photo_file_id == "photo-1"
