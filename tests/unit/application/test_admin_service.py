"""AdminService: owner queue gates; no deliver after supersede; CAS + authZ."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from diana.application.admin_service import AdminService, OwnerAuthError
from diana.application.memory import (
    FakeOwnerNotifier,
    InMemoryEscalationStore,
    InMemoryMessageHistoryWriter,
    InMemoryPendingApprovalStore,
    InMemoryPendingDeliveryStore,
    InMemoryTraceReaderWriter,
    InMemoryTurnStore,
)
from diana.application.staging_service import StagingService
from diana.application.turn_coordinator import TurnCoordinator
from diana.behavior.engine import BehaviorEngine
from diana.behavior.fake import (
    AlwaysLiveTurnStatusReader,
    FakeTelegramActuator,
    FixedDelayPolicy,
    ImmediateClock,
    SequenceTurnStatusReader,
)
from diana.cognitive.models import Decision, EvaluationProfile, IncomingTurn

OWNER_ID = 999001
OTHER_USER = 111

# Minimal six-profile catalog for SandboxService unit tests.
_MINIMAL_SIX = {
    "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
    "cercano": {
        "label": "VIP cercano",
        "description": "",
        "facts": {"name": "Mateo", "personality": "confiado"},
        "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
    },
    "distante": {
        "label": "VIP reservado",
        "description": "",
        "facts": {"personality": "formal"},
        "notes": [],
    },
    "intenso": {
        "label": "VIP emocional",
        "description": "",
        "facts": {"relationship": "recién separado"},
        "notes": [],
    },
    "vip_largo": {
        "label": "VIP largo",
        "description": "",
        "facts": {"name": "Sofía"},
        "notes": [],
    },
    "inyeccion_previa": {
        "label": "Fixture adversarial",
        "description": "",
        "facts": {"name": "TestUser"},
        "notes": [],
    },
}


def _real_staging(
    *,
    insert_return: object | None = None,
    insert_side_effect: BaseException | None = None,
    sandbox: object | None = None,
) -> tuple[StagingService, AsyncMock]:
    """Real StagingService with repo mocked at the infrastructure border."""
    staging_repo = AsyncMock()
    if insert_side_effect is not None:
        staging_repo.insert = AsyncMock(side_effect=insert_side_effect)
    else:
        row = (
            insert_return
            if insert_return is not None
            else SimpleNamespace(id=uuid4())
        )
        staging_repo.insert = AsyncMock(return_value=row)
    service = StagingService(
        staging_repo=staging_repo,
        examples_repo=AsyncMock(),
        policies_repo=AsyncMock(),
        sandbox=sandbox,
    )
    return service, staging_repo


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


def _decision(action: str = "approve", draft: str = "hola VIP") -> Decision:
    return Decision(
        action=action,  # type: ignore[arg-type]
        reason="ok",
        evaluation=_eval(),
        draft_text=draft,
    )


def _admin_graph(
    *,
    feature_advanced_behavior: bool = False,
    behavior_override: object | None = None,
    vip_store: object | None = None,
    delivery_mode: str = "supervised",
    staging: object | None = None,
    history: object | None = None,
) -> dict:
    from diana.application.memory import InMemoryVipStore

    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    vips = vip_store if vip_store is not None else InMemoryVipStore()
    behavior = behavior_override or BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=AlwaysLiveTurnStatusReader(),
        feature_advanced_behavior=feature_advanced_behavior,
    )
    from diana.application.approval_ui import ApprovalDraftVoider

    coordinator = TurnCoordinator(
        turns,
        approvals,
        behavior,  # type: ignore[arg-type]
        approval_ui=ApprovalDraftVoider(notifier),
    )
    admin = AdminService(
        notifier=notifier,
        approvals=approvals,
        escalations=escalations,
        coordinator=coordinator,
        behavior=behavior,  # type: ignore[arg-type]
        traces=traces,
        turns=turns,
        owner_telegram_id=OWNER_ID,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        feature_advanced_behavior=feature_advanced_behavior,
        vip_store=vips,  # type: ignore[arg-type]
        staging=staging,  # type: ignore[arg-type]
        history=history,  # type: ignore[arg-type]
    )
    return {
        "admin": admin,
        "turns": turns,
        "approvals": approvals,
        "coordinator": coordinator,
        "notifier": notifier,
        "actuator": actuator,
        "behavior": behavior,
        "traces": traces,
        "escalations": escalations,
        "deliveries": deliveries,
        "owner_id": OWNER_ID,
        "vip_store": vips,
        "staging": staging,
        "history": history,
    }


@pytest.fixture
def admin_graph() -> dict:
    return _admin_graph()


def _incoming(turn_id, **kw) -> IncomingTurn:
    data = {
        "turn_id": turn_id,
        "chat_id": 42,
        "text": "vip says hi",
        "business_connection_id": "bc-1",
        "telegram_message_id": 7,
    }
    data.update(kw)
    return IncomingTurn(**data)


@pytest.mark.asyncio
async def test_send_draft_for_approval_notifies_and_persists(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    decision = _decision(draft="draft text")
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), decision, turn.id
    )
    assert len(g["notifier"].drafts) == 1
    assert g["notifier"].drafts[0].draft_text == "draft text"
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None
    assert appr.status == "waiting"
    assert appr.draft_text == "draft text"
    assert appr.owner_message_id == 5000
    assert appr.trigger_message_id == 7


@pytest.mark.asyncio
async def test_handle_approve_delivers_and_marks_delivered(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    decision = _decision(draft="send me")
    await g["admin"].send_draft_for_approval(_incoming(turn.id), decision, turn.id)
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None
    assert result.success is True
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "send me"
    # mark-as-read plumbing
    ops = [c["op"] for c in g["actuator"].calls]
    assert "read_business_message" in ops
    assert g["actuator"].calls[0]["message_id"] == 7
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "delivered"
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.status == "approved"
    assert g["traces"].get_delivery_result(turn.id) is not None


@pytest.mark.asyncio
async def test_handle_correct_delivers_corrected_not_draft(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="original draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_correct(
        turn.id, "corrected final", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "corrected final"
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.status == "corrected"
    assert g["admin"]._staging is None  # noqa: SLF001 — default optional dep


@pytest.mark.asyncio
async def test_handle_correct_saves_staging_candidate() -> None:
    """H7.1: handle_correct persists pending staging before deliver (timing A).

    Uses real StagingService; only StagingCandidateRepo is mocked (infra border).
    Asserts chat_id= reaches save_correction (sandbox isolation wiring).
    """
    staging, staging_repo = _real_staging()
    save_spy = AsyncMock(wraps=staging.save_correction)
    staging.save_correction = save_spy  # type: ignore[method-assign]
    history = InMemoryMessageHistoryWriter()
    await history.append(
        42, role="vip", text="vip trigger text", telegram_message_id=7
    )
    g = _admin_graph(staging=staging, history=history)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, telegram_message_id=7),
        _decision(draft="original draft"),
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_correct(
        turn.id, "corrected final", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    # Real StagingService.save_correction → repo.insert(type, payload, turn_id)
    staging_repo.insert.assert_awaited_once()
    insert_args = staging_repo.insert.await_args
    assert insert_args.args[0] == "example"
    payload = insert_args.args[1]
    assert payload["original_draft"] == "original draft"
    assert payload["corrected_text"] == "corrected final"
    assert payload["context"]["chat_id"] == 42
    assert payload["context"]["turn_text"] == "vip trigger text"
    assert insert_args.args[2] == turn.id
    # REQ-ATN-13: channel_type flows from the turn into the staging payload.
    assert payload["channel_type"] == "vip"
    # PLAN DoD: keyword-only chat_id= for sandbox isolation.
    save_spy.assert_awaited_once()
    assert save_spy.await_args.kwargs["chat_id"] == turn.chat_id
    assert save_spy.await_args.kwargs["channel_type"] == turn.channel_type
    # Delivery still happened after staging (timing A).
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "corrected final"


@pytest.mark.asyncio
async def test_handle_correct_sandbox_skips_staging_still_delivers() -> None:
    """H7: active sandbox → save_correction skips insert; VIP deliver still succeeds."""
    from diana.application.sandbox import SandboxService

    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(42, "nuevo")
    staging, staging_repo = _real_staging(sandbox=sandbox)
    history = InMemoryMessageHistoryWriter()
    g = _admin_graph(staging=staging, history=history)
    g["admin"]._sandbox = sandbox  # noqa: SLF001
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_correct(
        turn.id, "sandbox corrected", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    assert g["actuator"].send_count() == 1
    staging_repo.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_correct_skips_staging_when_none(admin_graph: dict) -> None:
    """H7: staging None is a no-op; correct still delivers."""
    g = admin_graph
    assert g["admin"]._staging is None  # noqa: SLF001
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_correct(
        turn.id, "fixed text", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    assert g["actuator"].calls[-1]["text"] == "fixed text"


@pytest.mark.asyncio
async def test_handle_correct_staging_failure_still_delivers() -> None:
    """H7: staging I/O failure must not block VIP delivery."""
    staging, staging_repo = _real_staging(
        insert_side_effect=RuntimeError("db down")
    )
    g = _admin_graph(staging=staging)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_correct(
        turn.id, "still deliver", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    assert g["actuator"].send_count() == 1
    assert g["actuator"].calls[-1]["text"] == "still deliver"
    staging_repo.insert.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_approve_appends_owner_history() -> None:
    """H7.2: successful approve appends role=owner with draft text."""
    history = InMemoryMessageHistoryWriter()
    g = _admin_graph(history=history)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="approved draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success
    rows = await history.get_recent(42)
    owner_rows = [r for r in rows if r.get("role") == "owner"]
    assert len(owner_rows) == 1
    assert owner_rows[0]["text"] == "approved draft"


@pytest.mark.asyncio
async def test_handle_correct_appends_owner_history_with_corrected_text() -> None:
    """H7.2: successful correct appends role=owner with corrected text, not draft."""
    history = InMemoryMessageHistoryWriter()
    g = _admin_graph(history=history)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="original draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_correct(
        turn.id, "owner fix", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    rows = await history.get_recent(42)
    owner_rows = [r for r in rows if r.get("role") == "owner"]
    assert len(owner_rows) == 1
    assert owner_rows[0]["text"] == "owner fix"


@pytest.mark.asyncio
async def test_approve_sandbox_skips_owner_history() -> None:
    """Sandbox active: successful approve must not pollute durable owner history."""
    from diana.application.sandbox import SandboxService

    history = InMemoryMessageHistoryWriter()
    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(42, "cercano")
    g = _admin_graph(history=history)
    g["admin"]._sandbox = sandbox  # noqa: SLF001
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="sandbox outbound"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success
    rows = await history.get_recent(42)
    assert not any(r.get("role") == "owner" for r in rows)


class _MultiMidDeliverer:
    """Spy BehaviorDeliverer returning multi-segment DeliveryResult."""

    def __init__(
        self,
        *,
        message_ids: list[int] | None = None,
        texts: list[str] | None = None,
    ) -> None:
        from diana.application.ports import DeliveryResult

        self.message_ids = message_ids if message_ids is not None else [10, 11, 12]
        self.segment_texts = (
            texts if texts is not None else ["seg-a", "seg-b", "seg-c"]
        )
        self.ctxs: list = []
        self._DeliveryResult = DeliveryResult

    async def deliver(
        self,
        texts: list[str],
        ctx: object,
        turn_id: object,
        decision: object | None = None,
    ) -> object:
        self.ctxs.append(ctx)
        return self._DeliveryResult(
            success=True,
            message_ids=list(self.message_ids),
            texts=list(self.segment_texts),
        )


@pytest.mark.asyncio
async def test_approve_multi_message_ids_appends_all_owner_history() -> None:
    """Successful multi-segment deliver writes one owner row per message_id."""
    history = InMemoryMessageHistoryWriter()
    spy = _MultiMidDeliverer(
        message_ids=[10, 11, 12],
        texts=["seg-a", "seg-b", "seg-c"],
    )
    g = _admin_graph(history=history, behavior_override=spy)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="full draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success
    rows = await history.get_recent(42)
    owner_rows = [r for r in rows if r.get("role") == "owner"]
    assert len(owner_rows) == 3
    assert [r["text"] for r in owner_rows] == ["seg-a", "seg-b", "seg-c"]
    assert [r["telegram_message_id"] for r in owner_rows] == [10, 11, 12]


@pytest.mark.asyncio
async def test_approve_empty_message_ids_appends_owner_once_mid_none() -> None:
    """Fake delivery (empty message_ids) still appends once with mid=None."""
    history = InMemoryMessageHistoryWriter()
    spy = _MultiMidDeliverer(message_ids=[], texts=[])
    g = _admin_graph(history=history, behavior_override=spy)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="fake draft full"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success
    rows = await history.get_recent(42)
    owner_rows = [r for r in rows if r.get("role") == "owner"]
    assert len(owner_rows) == 1
    assert owner_rows[0]["text"] == "fake draft full"
    assert owner_rows[0].get("telegram_message_id") is None


@pytest.mark.asyncio
async def test_approve_multi_mid_sandbox_skips_all_owner_history() -> None:
    """Sandbox active + multi-mid success → zero owner rows (gate once)."""
    from diana.application.sandbox import SandboxService

    history = InMemoryMessageHistoryWriter()
    sandbox = SandboxService(profiles=_MINIMAL_SIX)
    sandbox.activate(42, "cercano")
    spy = _MultiMidDeliverer(
        message_ids=[10, 11, 12],
        texts=["seg-a", "seg-b", "seg-c"],
    )
    g = _admin_graph(history=history, behavior_override=spy)
    g["admin"]._sandbox = sandbox  # noqa: SLF001
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="sandbox multi"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success
    rows = await history.get_recent(42)
    assert not any(r.get("role") == "owner" for r in rows)


@pytest.mark.asyncio
async def test_resolve_no_history_on_delivery_failure() -> None:
    """H7.2: frozen / failed resolve must not write owner history."""
    from datetime import UTC, datetime, timedelta

    from diana.application.memory import InMemoryVipStore

    history = InMemoryMessageHistoryWriter()
    store = InMemoryVipStore()
    vip = await store.add(43001, display_name="FrozenForHistory")
    await store.freeze_vip(vip.id, datetime.now(UTC) + timedelta(hours=2))
    g = _admin_graph(history=history, vip_store=store)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, vip_id=vip.id),
        _decision(draft="should not history"),
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None
    assert result.success is False
    rows = await history.get_recent(42)
    assert not any(r.get("role") == "owner" for r in rows)


@pytest.mark.asyncio
async def test_resolve_no_history_on_claim_lost_supersede() -> None:
    """H7.2: claim-lost / superseded approve must not write owner history."""
    history = InMemoryMessageHistoryWriter()
    g = _admin_graph(history=history)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="old draft"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    await g["coordinator"].begin_turn(chat_id=42)  # supersede → claim lost
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is None
    assert g["actuator"].send_count() == 0
    rows = await history.get_recent(42)
    assert not any(r.get("role") == "owner" for r in rows)


@pytest.mark.asyncio
async def test_handle_correct_turn_text_empty_without_history_match() -> None:
    """H7: missing history match → context turn_text is empty string."""
    staging, staging_repo = _real_staging()
    # No history injected → _resolve_trigger_text returns ""
    g = _admin_graph(staging=staging, history=None)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=99)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, telegram_message_id=99),
        _decision(draft="draft"),
        turn.id,
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_correct(
        turn.id, "corrected", actor_id=OWNER_ID
    )
    assert result is not None and result.success
    staging_repo.insert.assert_awaited_once()
    payload = staging_repo.insert.await_args.args[1]
    assert payload["context"]["turn_text"] == ""

@pytest.mark.asyncio
async def test_handle_approve_after_supersede_no_deliver(admin_graph: dict) -> None:
    g = admin_graph
    a = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(a.id), _decision(draft="old"), a.id
    )
    await g["coordinator"].transition(a.id, "pending_approval")
    await g["coordinator"].begin_turn(chat_id=42)  # supersede A
    result = await g["admin"].handle_approve(a.id, actor_id=OWNER_ID)
    assert result is None
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_supersede_voids_owner_draft_dm(admin_graph: dict) -> None:
    """C3/A3: superseding a waiting draft prepends cancel legend, keeps the body."""
    g = admin_graph
    a = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(a.id), _decision(draft="old"), a.id
    )
    await g["coordinator"].transition(a.id, "pending_approval")
    approval = await g["approvals"].get_by_turn(a.id)
    assert approval is not None
    assert approval.owner_message_id is not None

    await g["coordinator"].begin_turn(chat_id=42)  # supersede A → void UI

    approval_after = await g["approvals"].get_by_turn(a.id)
    assert approval_after is not None
    assert approval_after.status == "cancelled"
    assert len(g["notifier"].voids) == 1
    mid, text = g["notifier"].voids[0]
    assert mid == approval.owner_message_id
    assert "cancelado" in text.lower()
    # Draft body is preserved for audit, not erased by the void notice.
    assert "[propuesta]: old" in text
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_notify_escalation_creates_event(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    decision = Decision(
        action="escalate",
        reason="safety",
        evaluation=_eval(),
        draft_text="",
    )
    await g["admin"].notify_escalation(_incoming(turn.id), decision, turn.id)
    assert len(g["notifier"].escalations) == 1
    assert g["escalations"].events
    assert g["escalations"].events[0]["tipo"] == "semantica"


@pytest.mark.asyncio
async def test_send_draft_requires_business_connection_id(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    with pytest.raises(ValueError, match="business_connection_id"):
        await g["admin"].send_draft_for_approval(
            _incoming(turn.id, business_connection_id=None),
            _decision(),
            turn.id,
        )


@pytest.mark.asyncio
async def test_non_owner_approve_rejected(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="x"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    with pytest.raises(OwnerAuthError):
        await g["admin"].handle_approve(turn.id, actor_id=OTHER_USER)
    with pytest.raises(OwnerAuthError):
        await g["admin"].handle_approve(turn.id, actor_id=None)
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_concurrent_double_approve_single_send(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="once"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")

    r1, r2 = await asyncio.gather(
        g["admin"].handle_approve(turn.id, actor_id=OWNER_ID),
        g["admin"].handle_approve(turn.id, actor_id=OWNER_ID),
    )
    successes = [r for r in (r1, r2) if r is not None and r.success]
    assert len(successes) == 1
    assert g["actuator"].send_count() == 1
    stored = await g["turns"].get(turn.id)
    assert stored is not None and stored.status == "delivered"


@pytest.mark.asyncio
async def test_empty_correct_rejected(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="x"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    with pytest.raises(ValueError, match="corrected_text"):
        await g["admin"].handle_correct(turn.id, "   ", actor_id=OWNER_ID)
    assert g["actuator"].send_count() == 0


@pytest.mark.asyncio
async def test_terminal_latch_blocks_revive(admin_graph: dict) -> None:
    g = admin_graph
    a = await g["coordinator"].begin_turn(chat_id=42)
    await g["coordinator"].transition(a.id, "pending_approval")
    b = await g["coordinator"].begin_turn(chat_id=42)
    assert b.id != a.id
    revived = await g["coordinator"].transition(a.id, "pending_approval")
    assert revived.status == "superseded"
    assert revived.superseded_by == b.id


@pytest.mark.asyncio
async def test_permanent_deliver_fail_marks_failed_and_notifies() -> None:
    """I.5: permanent delivery failure → Turn.failed + owner notify + no waiting reopen."""
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()

    class BoomActuator(FakeTelegramActuator):
        async def send_message(
            self,
            chat_id: int,
            text: str,
            *,
            business_connection_id: str,
            parse_mode: str | None = None,
        ) -> int:
            raise RuntimeError("telegram_down")

    actuator = BoomActuator()
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=AlwaysLiveTurnStatusReader(),
        max_send_attempts=3,
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
        owner_telegram_id=OWNER_ID,
    )
    turn = await coordinator.begin_turn(chat_id=42, trigger_message_id=7)
    await admin.send_draft_for_approval(
        _incoming(turn.id), _decision(draft="fail me"), turn.id
    )
    await coordinator.transition(turn.id, "pending_approval")
    result = await admin.handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None
    assert result.success is False
    assert result.cancelled is False
    stored = await turns.get(turn.id)
    assert stored is not None and stored.status == "failed"
    appr = await approvals.get_by_turn(turn.id)
    assert appr is not None and appr.status == "cancelled"
    assert appr.status != "waiting"
    assert any(
        "delivery_failed" in text or "failed" in text.lower()
        for text, _ in notifier.infos
    )
    assert traces.get_delivery_result(turn.id) is not None


@pytest.mark.asyncio
async def test_supersede_mid_flight_does_not_mark_failed() -> None:
    """Cancelled/superseded path must not force Turn.failed (L8)."""
    turns = InMemoryTurnStore()
    approvals = InMemoryPendingApprovalStore()
    deliveries = InMemoryPendingDeliveryStore()
    escalations = InMemoryEscalationStore()
    traces = InMemoryTraceReaderWriter()
    notifier = FakeOwnerNotifier()
    actuator = FakeTelegramActuator()
    # First pre-send sees live, but we supersede via status before send:
    # reader returns superseded → cancelled, no failed.
    behavior = BehaviorEngine(
        actuator,
        deliveries,
        clock=ImmediateClock(),
        delay_policy=FixedDelayPolicy(),
        turn_status=SequenceTurnStatusReader(["superseded"]),
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
        owner_telegram_id=OWNER_ID,
    )
    a = await coordinator.begin_turn(chat_id=42, trigger_message_id=7)
    await admin.send_draft_for_approval(
        _incoming(a.id), _decision(draft="old"), a.id
    )
    await coordinator.transition(a.id, "pending_approval")
    # Supersede A before approve completes post-latch.
    b = await coordinator.begin_turn(chat_id=42)
    assert b.id != a.id
    result = await admin.handle_approve(a.id, actor_id=OWNER_ID)
    # Terminal latch: claim may still run if still pending_approval was superseded
    # begin_turn already terminal-latched A to superseded → approve returns None
    # OR if claim won earlier path: cancelled result without failed.
    stored = await turns.get(a.id)
    assert stored is not None
    assert stored.status == "superseded"
    assert stored.status != "failed"
    assert actuator.send_count() == 0
    # No false failed notify for supersede
    failed_infos = [t for t, _ in notifier.infos if "delivery_failed" in t]
    assert failed_infos == []
    _ = result


# ── send_doctrine_query (F2 gray zone) ──────────────────────────────────


def _make_query_view(*, query_id: UUID | None = None) -> object:
    """Build a minimal GrayZoneQueryView-compatible object."""
    return type("_Query", (), {"id": query_id})() if query_id is not None else type("_Query", (), {"id": None})()


@pytest.mark.asyncio
async def test_send_doctrine_query_success(admin_graph: dict) -> None:
    """Happy path: doctrine query creates notification and records owner_mid."""
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    d = _decision(action="consult_doctrine", draft="doctrine draft")
    await g["admin"].send_doctrine_query(
        _incoming(turn.id), d, turn.id, _make_query_view(query_id=uuid4())
    )
    assert len(g["notifier"].doctrines) == 1
    payload = g["notifier"].doctrines[0]
    assert payload.turn_id == turn.id
    assert payload.draft_text == "doctrine draft"
    assert payload.business_connection_id == "bc-1"
    assert payload.reply_markup_spec is not None
    assert "actions" in payload.reply_markup_spec
    assert "respond_doctrine" in payload.reply_markup_spec["actions"]


@pytest.mark.asyncio
async def test_send_doctrine_query_missing_bc_raises(admin_graph: dict) -> None:
    """Missing business_connection_id should raise ValueError."""
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    d = _decision(action="consult_doctrine")
    with pytest.raises(ValueError, match="business_connection_id"):
        await g["admin"].send_doctrine_query(
            _incoming(turn.id, business_connection_id=None),
            d,
            turn.id,
            _make_query_view(query_id=uuid4()),
        )


@pytest.mark.asyncio
async def test_send_doctrine_query_adds_query_id_when_present(admin_graph: dict) -> None:
    """reply_markup_spec includes query_id when available, omits when None."""
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    d = _decision(action="consult_doctrine")
    qid = uuid4()
    await g["admin"].send_doctrine_query(
        _incoming(turn.id), d, turn.id, _make_query_view(query_id=qid)
    )
    assert len(g["notifier"].doctrines) == 1
    spec = g["notifier"].doctrines[0].reply_markup_spec
    assert spec is not None
    assert spec.get("query_id") == str(qid)


@pytest.mark.asyncio
async def test_send_doctrine_query_omits_query_id_when_none(admin_graph: dict) -> None:
    """When query.id is None, query_id key is absent from reply_markup_spec."""
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    d = _decision(action="consult_doctrine")
    await g["admin"].send_doctrine_query(
        _incoming(turn.id), d, turn.id, _make_query_view(query_id=None)
    )
    assert len(g["notifier"].doctrines) == 1
    spec = g["notifier"].doctrines[0].reply_markup_spec
    assert spec is not None
    assert "query_id" not in spec


# --- Item4 Task4: advanced behavior builder wiring ---


class _CapturingDeliverer:
    def __init__(self) -> None:
        self.ctxs: list = []

    async def deliver(
        self,
        texts: list[str],
        ctx: object,
        turn_id: object,
        decision: object | None = None,
    ) -> object:
        from diana.application.ports import DeliveryResult

        self.ctxs.append(ctx)
        return DeliveryResult(success=True, message_ids=[1])


@pytest.mark.asyncio
async def test_admin_advanced_flag_on_sets_allow_on_deliver_ctx() -> None:
    spy = _CapturingDeliverer()
    g = _admin_graph(feature_advanced_behavior=True, behavior_override=spy)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="send me"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success is True
    assert len(spy.ctxs) == 1
    ctx = spy.ctxs[0]
    assert ctx.allow_split is True
    assert ctx.allow_human_quirks is True
    assert ctx.split_chars == 4096


@pytest.mark.asyncio
async def test_admin_advanced_flag_off_allow_defaults_false() -> None:
    spy = _CapturingDeliverer()
    g = _admin_graph(feature_advanced_behavior=False, behavior_override=spy)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="send me"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success is True
    assert len(spy.ctxs) == 1
    ctx = spy.ctxs[0]
    assert ctx.allow_split is False
    assert ctx.allow_human_quirks is False
    assert ctx.split_chars == 4096


@pytest.mark.asyncio
async def test_admin_short_text_one_send_flag_off_regression(admin_graph: dict) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="short"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success is True
    sends = [c for c in g["actuator"].calls if c["op"] == "send_message"]
    assert len(sends) == 1
    assert sends[0]["text"] == "short"


@pytest.mark.asyncio
async def test_admin_approve_frozen_vip_skips_deliver() -> None:
    """SEC-F1: frozen VIP → no send, turn failed, approval cancelled."""
    from datetime import UTC, datetime, timedelta

    from diana.application.memory import InMemoryVipStore

    store = InMemoryVipStore()
    vip = await store.add(42001, display_name="FrozenVIP")
    await store.freeze_vip(vip.id, datetime.now(UTC) + timedelta(hours=2))
    spy = _CapturingDeliverer()
    g = _admin_graph(behavior_override=spy, vip_store=store)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, vip_id=vip.id),
        _decision(draft="should not send"),
        turn.id,
    )
    appr = await g["approvals"].get_by_turn(turn.id)
    assert appr is not None and appr.vip_id == vip.id
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None
    assert result.success is False
    assert result.cancelled is True
    assert result.error == "vip_frozen"
    assert spy.ctxs == []  # never called deliver
    assert g["actuator"].send_count() == 0
    stored = await g["turns"].get(turn.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error == "vip_frozen"
    appr_after = await g["approvals"].get_by_turn(turn.id)
    assert appr_after is not None
    assert appr_after.status == "cancelled"


@pytest.mark.asyncio
async def test_admin_deliver_ctx_is_frozen_false_when_unfrozen() -> None:
    """SEC-F2: unfrozen path sets DeliveryContext.is_frozen=False."""
    spy = _CapturingDeliverer()
    g = _admin_graph(behavior_override=spy)
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id), _decision(draft="ok"), turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None and result.success is True
    assert len(spy.ctxs) == 1
    assert spy.ctxs[0].is_frozen is False



@pytest.mark.asyncio
async def test_mark_false_positive_records_owner_mark() -> None:
    """R5: owner can mark a turn as false-positive escalation."""
    from diana.application.owner_marks import InMemoryOwnerMarkStore
    from datetime import date

    g = _admin_graph()
    marks = InMemoryOwnerMarkStore()
    g["admin"]._fp_marks = marks  # noqa: SLF001
    turn_id = uuid4()
    ok = await g["admin"].mark_false_positive(turn_id, actor_id=OWNER_ID)
    assert ok is True
    assert await marks.count_in_range(date(2000, 1, 1), date(2100, 1, 1)) == 1


@pytest.mark.asyncio
async def test_mark_false_positive_rejects_non_owner() -> None:
    from diana.application.owner_marks import InMemoryOwnerMarkStore

    g = _admin_graph()
    g["admin"]._fp_marks = InMemoryOwnerMarkStore()  # noqa: SLF001
    with pytest.raises(OwnerAuthError):
        await g["admin"].mark_false_positive(uuid4(), actor_id=OTHER_USER)


@pytest.mark.asyncio
async def test_mark_false_positive_noop_without_store() -> None:
    g = _admin_graph()
    # no fp_marks wired
    ok = await g["admin"].mark_false_positive(uuid4(), actor_id=OWNER_ID)
    assert ok is False

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason,expected_tipo",
    [
        ("frustracion_directa", "frustracion_directa"),
        ("pregunta_repetida", "pregunta_repetida"),
        ("pago_precio", "pago_precio"),
        ("compromiso_real", "compromiso_real"),
        ("identidad_ia", "identidad_ia"),
        ("palabra_prohibida", "palabra_prohibida"),
        ("safety_below_threshold", "semantica"),
    ],
)
async def test_notify_escalation_maps_system_reason_to_tipo(
    admin_graph: dict, reason: str, expected_tipo: str
) -> None:
    g = admin_graph
    turn = await g["coordinator"].begin_turn(chat_id=42)
    decision = Decision(
        action="escalate",
        reason=reason,
        evaluation=_eval(),
        draft_text="",
    )
    await g["admin"].notify_escalation(_incoming(turn.id), decision, turn.id)
    assert g["escalations"].events[0]["tipo"] == expected_tipo
    assert g["notifier"].escalations[0].tipo == expected_tipo



# ── Sandbox marker + configured delivery_mode ───────────────────────────


@pytest.mark.asyncio
async def test_sandbox_draft_reason_has_marker() -> None:

    from diana.application.sandbox import SandboxService
    # inline six-profile catalog
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    g = _admin_graph()
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(42, "cercano")
    g["admin"]._sandbox = sandbox  # noqa: SLF001
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    decision = _decision(draft="sandbox draft")
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, chat_id=42), decision, turn.id
    )
    assert len(g["notifier"].drafts) == 1
    reason = g["notifier"].drafts[0].reason
    assert reason.startswith("SANDBOX — profile: cercano")


@pytest.mark.asyncio
async def test_sandbox_approve_uses_configured_delivery_mode() -> None:
    """Sandbox must not force fake_delivery; mode equals AdminService delivery_mode."""
    from diana.application.sandbox import SandboxService
    # inline six-profile catalog
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }
    from diana.application.ports import DeliveryResult

    captured: list = []

    class CaptureBehavior:
        async def deliver(self, texts, ctx, turn_id, **kwargs):
            captured.append(ctx)
            return DeliveryResult(success=True, cancelled=False)

        async def cancel_pending(self, chat_id, reason):
            return 0

    g = _admin_graph(behavior_override=CaptureBehavior())
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(42, "intenso")
    g["admin"]._sandbox = sandbox  # noqa: SLF001
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    decision = _decision(draft="send me")
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, chat_id=42), decision, turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None
    assert result.success is True
    assert len(captured) == 1
    # CLARIFY: sandbox must not force fake — equals configured delivery_mode
    assert captured[0].mode == "supervised"


@pytest.mark.asyncio
async def test_sandbox_admin_respects_fake_delivery_mode() -> None:
    """Sandbox active + AdminService delivery_mode=fake_delivery still yields fake (D6)."""
    from diana.application.sandbox import SandboxService
    from diana.application.ports import DeliveryResult

    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    captured: list = []

    class CaptureBehavior:
        async def deliver(self, texts, ctx, turn_id, **kwargs):
            captured.append(ctx)
            return DeliveryResult(success=True, cancelled=False)

        async def cancel_pending(self, chat_id, reason):
            return 0

    g = _admin_graph(
        behavior_override=CaptureBehavior(),
        delivery_mode="fake_delivery",
    )
    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(42, "intenso")
    g["admin"]._sandbox = sandbox  # noqa: SLF001
    turn = await g["coordinator"].begin_turn(chat_id=42, trigger_message_id=7)
    decision = _decision(draft="send me")
    await g["admin"].send_draft_for_approval(
        _incoming(turn.id, chat_id=42), decision, turn.id
    )
    await g["coordinator"].transition(turn.id, "pending_approval")
    result = await g["admin"].handle_approve(turn.id, actor_id=OWNER_ID)
    assert result is not None
    assert result.success is True
    assert len(captured) == 1
    assert captured[0].mode == "fake_delivery"
